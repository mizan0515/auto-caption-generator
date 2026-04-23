import logging
import re
import requests
import json
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

NAVER_API = "https://apis.naver.com"
CHZZK_API = "https://api.chzzk.naver.com"
VIDEOHUB_API = "https://api-videohub.naver.com"

_logger = logging.getLogger(__name__)

# 같은 런 안에서 쿠키 갱신이 한 번 터진 뒤 무한 재시도하지 않도록 가드.
_refresh_attempted = False


def _maybe_refresh_cookies(cookies: dict) -> bool:
    """401/403 응답 시 브라우저에서 NID_AUT/NID_SES 를 재추출해 cookies 를 in-place 갱신.

    런 1회 한정. 성공 시 True 를 돌려주고 호출측이 원래 요청을 재시도한다.
    cookies dict 를 직접 변경하므로, 이후 같은 세션의 다른 요청도 자동으로 새 쿠키 사용.
    """
    global _refresh_attempted
    if _refresh_attempted:
        return False
    _refresh_attempted = True

    try:
        from pipeline.cookie_refresh import refresh_cookies  # lazy: 배포 전후 의존성 순환 회피
        from pipeline.config import load_config
    except Exception as e:  # noqa: BLE001
        _logger.warning(f"쿠키 자동 갱신 모듈 로드 실패: {e}")
        return False

    try:
        ok, reason = refresh_cookies()
        _logger.warning(f"인증 실패 감지 → 쿠키 자동 갱신 시도: {reason}")
        if not ok:
            return False
        cfg = load_config()
        new_cookies = cfg.get("cookies") or {}
        if not (new_cookies.get("NID_AUT") and new_cookies.get("NID_SES")):
            return False
        # 호출측 dict 를 직접 mutate → 이후 NetworkManager 호출들도 새 쿠키 사용
        cookies.clear()
        cookies.update(new_cookies)
        return True
    except Exception as e:  # noqa: BLE001
        _logger.warning(f"쿠키 자동 갱신 예외: {e}")
        return False


def _get_with_auth_retry(url: str, cookies: dict, **kwargs) -> requests.Response:
    """requests.get 래퍼 — 401/403 이면 쿠키 재추출 후 1회 재시도.

    cookies 가 dict 가 아니거나 재시도가 무의미하면 그냥 requests.get 과 동일.
    """
    response = requests.get(url, cookies=cookies, **kwargs)
    if response.status_code in (401, 403) and isinstance(cookies, dict):
        if _maybe_refresh_cookies(cookies):
            response = requests.get(url, cookies=cookies, **kwargs)
    return response

class NetworkManager:

    @staticmethod
    def extract_content_no(vod_url: str) -> tuple[str, str]:
        """
        치지직 VOD URL에서 type과 content_no를 추출한다.
        
        Args:
            vod_url (str): 치지직 VOD URL
            
        Returns:
            tuple[str, str]: (type, content_no) 형식의 튜플. 매칭되지 않으면 (None, None) 반환
        """
        if not vod_url.startswith("http://") and not vod_url.startswith("https://"):
            vod_url = "https://" + vod_url
        match = re.fullmatch(r'https?://chzzk\.naver\.com/(?P<content_type>video|clips)/(?P<content_no>\w+)', vod_url)
        if match:
            return match.group("content_type"), match.group("content_no")
        return None, None

    @staticmethod
    def get_video_info(video_no: str, cookies: dict):
        """
        API를 통해 video_no에 대응하는 video_id, in_key, 메타데이터를 가져온다.
        """
        api_url = f"{CHZZK_API}/service/v2/videos/{video_no}"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = _get_with_auth_retry(api_url, cookies=cookies, headers=headers)
        response.raise_for_status()

        content = response.json().get('content', {})
        video_id = content.get('videoId')
        in_key = content.get('inKey')
        adult = content.get('adult')
        vodStatus = content.get('vodStatus')
        liveRewindPlaybackJson = content.get('liveRewindPlaybackJson')

        metadata = {
            'title': re.sub(r'[\\/:\*\?"<>|\n]', '', content.get('videoTitle', 'Unknown Title')), # 정규식으로 특수문자 제거
            'thumbnailImageUrl': content.get('thumbnailImageUrl', ''),
            'category': content.get('videoCategoryValue', 'Unknown Category'),
            'channelId': content.get('channel', {}).get('channelId', ''),
            'channelName': content.get('channel', {}).get('channelName', 'Unknown Channel'),
            'channelImageUrl': content.get('channel', {}).get('channelImageUrl', ''),
            'createdDate': content.get('liveOpenDate', 'Unknown Date'),
            'duration': content.get('duration', 0),
        }
        return video_id, in_key, adult, vodStatus, liveRewindPlaybackJson, metadata
    
    @staticmethod
    def get_video_dash_manifest(video_id: str, in_key: str):
        """
        DASH 매니페스트를 요청하여 Representation 목록을 파싱한다.
        """
        manifest_url = f"{NAVER_API}/neonplayer/vodplay/v2/playback/{video_id}?key={in_key}"
        headers = {"Accept": "application/dash+xml"}
        response = requests.get(manifest_url, headers=headers)
        response.raise_for_status()

        root = ET.fromstring(response.text)
        ns = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}
        reps = []
        for rep in root.findall(".//mpd:Representation", namespaces=ns):
            width = rep.get('width')
            height = rep.get('height')
            resolution = min(int(width), int(height))
            # print(width, height) # Debugging
            # print(f"Resolution: {resolution}") # Debugging
            base_url = rep.find(".//mpd:BaseURL", namespaces=ns).text
            if base_url.endswith('/hls/'):
                continue
            reps.append([resolution, base_url])
        
        sorted_reps = sorted(reps, key=lambda x: x[0])
        if not sorted_reps:
            return [], None, None
        auto_resolution = sorted_reps[-1][0]
        auto_base_url = sorted_reps[-1][1]

        # 중복 제거한 뒤, 리스트로 변환
        return sorted_reps, auto_resolution, auto_base_url

    @staticmethod
    def get_video_m3u8_manifest(json_str: str):
        """
        m3u8 정보가 포함된 json형식의 문자열을 받아서 Representation 목록을 파싱한다.
        """
        data = json.loads(json_str)
        media = data.get("media", [])
        if not media:
            return [], None, None
        encoding_track = media[0].get("encodingTrack", [])
        reps = []
        for encoding in encoding_track:
            width = encoding.get("videoWidth")
            height = encoding.get("videoHeight")
            if not width or not height:
                continue
            resolution = min(int(width), int(height))
            base_url = None
            reps.append([resolution, base_url])

        sorted_reps = sorted(reps, key=lambda x: x[0])
        if not sorted_reps:
            return [], None, None
        auto_resolution = sorted_reps[-1][0]
        auto_base_url = sorted_reps[-1][1]
        return sorted_reps, auto_resolution, auto_base_url
    
    @staticmethod
    def get_video_m3u8_base_url(json_str: str, resolution: int) -> str:
        """
        m3u8 정보가 포함된 json형식의 문자열을 받아서 base_url을 파싱한다.
        """
        data = json.loads(json_str)
        media = data.get("media", [])
        if not media:
            raise ValueError("m3u8 JSON에 media 배열이 비어있습니다.")
        path = media[0].get("path")
        if not path:
            raise ValueError("m3u8 media에 path가 없습니다.")
        response = requests.get(path)
        response.raise_for_status()
        content = response.text.splitlines()

        # 정규식으로 해상도 매칭
        resolution_pattern = re.compile(rf"RESOLUTION=\d+x{resolution}")
        
        for i, line in enumerate(content):
            if resolution_pattern.search(line):
                # 다음 줄이 해당 해상도의 세부 플레이리스트 경로
                if i + 1 >= len(content):
                    raise ValueError(
                        f"{resolution} 해상도 매칭 라인 뒤에 플레이리스트 경로가 없습니다."
                    )
                relative_path = content[i + 1].strip()
                if not relative_path:
                    raise ValueError(
                        f"{resolution} 해상도 플레이리스트 경로가 빈 문자열입니다."
                    )
                base_url = urljoin(path, relative_path)
                return base_url

        raise ValueError(f"{resolution} 해상도 스트림을 찾을 수 없습니다.")
    
    @staticmethod
    def get_clip_info(clip_no: str, cookies: dict):
        """
        API를 통해 clip_no에 대응하는 clip_id, in_key, 메타데이터를 가져온다.
        """
        api_url = f"{CHZZK_API}/service/v1/clips/{clip_no}/detail?optionalProperties=OWNER_CHANNEL"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = _get_with_auth_retry(api_url, cookies=cookies, headers=headers)
        response.raise_for_status()

        content = response.json().get('content', {})
        video_id = content.get('videoId')
        vodStatus = content.get('vodStatus')

        metadata = {
            'title': re.sub(r'[\\/:\*\?"<>|\n]', '', content.get('clipTitle', 'Unknown Title')), # 정규식으로 특수문자 제거
            'thumbnailImageUrl': content.get('thumbnailImageUrl', ''),
            'category': content.get('clipCategory', 'Unknown Category'),
            'channelName': content.get('optionalProperty', {}).get('ownerChannel', {}).get('channelName', 'Unknown Channel'),
            'channelImageUrl': content.get('optionalProperty', {}).get('ownerChannel', {}).get('channelImageUrl', ''),
            'createdDate': content.get('createdDate', 'Unknown Date'),
            'duration': content.get('duration', 0),
        }
        return video_id, vodStatus, metadata

    @staticmethod
    def get_clip_manifest(clip_id: str, cookies: dict):
        """
        DASH 매니페스트를 요청하여 Representation 목록을 파싱한다.
        """
        manifest_url = f"{VIDEOHUB_API}/shortformhub/feeds/v3/card?serviceType=CHZZK&seedMediaId={clip_id}&mediaType=VOD"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = _get_with_auth_retry(manifest_url, cookies=cookies, headers=headers)
        response.raise_for_status()

        data = response.json()

        resolutions = []

        #오류현상 예외처리

        content = data['card']['content']
        if 'error' in content:
            error = content['error']
            return None, None, None, error
        
        video_list = content['vod']['playback']['videos']['list']

        for video in video_list:
            encoding = video.get("encodingOption", {})
            width = encoding.get("width")
            height = encoding.get("height")
            source_url = video.get("source")

            if width and height and source_url:
                resolution = min(int(width), int(height))
                resolutions.append([resolution, source_url])

        sorted_resolutions = sorted(resolutions, key=lambda x: x[0])
        auto_resolution = sorted_resolutions[-1][0]
        auto_base_url = sorted_resolutions[-1][1]

        return sorted_resolutions, auto_resolution, auto_base_url, None