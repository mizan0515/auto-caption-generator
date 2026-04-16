# A4 Cross-Session Aggregation

Deterministic aggregation across three raw artifacts:
- `2026-04-15_phase-a4_raw.json`
- `2026-04-16_phase-a4_genre-acquisition_raw.json`
- `2026-04-16_phase-a4-acquisition-followup_raw.json`

## Labeling schema

`platform_category` (from Chzzk `videoCategoryValue`) is the authoritative axis label. `content_judgement` is an optional annotation. `promotion_axis_uses=platform_category`.

## Merged cells

| sample_id | length_min | genre | density_tier | platform_category | insufficient_data | median_user_ratio | P95_user_ratio |
|---|---|---|---|---|---|---|---|
| W1-30min-talk-high | 30 | talk | high | (unlabeled) | True | None | None |
| W2-1h-talk-medium | 60 | talk | medium | (unlabeled) | True | None | None |
| W3-3h-talk-low | 180 | talk | low | (unlabeled) | True | None | None |
| W4-offset1800s-game-nochat | 30 | game | none | (unlabeled) | True | 4.0621 | 4.1256 |
| W5-11688000-30min-olympics-nochat | 30 | olympics | none | (unlabeled) | False | 4.1179 | 4.6886 |
| W4f-offset1800s-12702452-chat | 30 | game | high | 더 게임 오브 라이프 포 닌텐도 스위치 | False | 2.8815 | 3.2994 |
| W5f-11688000-30min-chat | 30 | olympics | medium | 동계 올림픽 | False | 2.6337 | 2.9456 |

## Global aggregation

- template_hash: `4d732b40fa470862`
- covered_cell_count: **3**
- covered_lengths_min: [30]
- covered_genres: ['game', 'olympics']
- covered_density_tiers: ['high', 'medium', 'none']
- covered_platform_categories: ['더 게임 오브 라이프 포 닌텐도 스위치', '동계 올림픽'] (count=2)
- unlabeled_covered_sample_ids: ['W5-11688000-30min-olympics-nochat']
- global_median_P95: 3.2994
- dispersion_range: [2.8045, 3.7943]
- dispersion_failures: ['W5-11688000-30min-olympics-nochat']
- axis_coverage_ok: False
- dispersion_ok: False
- decision: **per_cell_multiplicative**
- recommended_margin: None

## Promotion readiness

Gate: `covered_cell_count>=5 AND covered_platform_category>=2 AND covered_density_tiers>=2 AND dispersion_ok`

- covered_cell_count: 3 (<5 FAIL)
- covered_platform_category_count: 2 (>=2 PASS)
- covered_density_tiers: 3 (>=2 PASS)
- dispersion_ok: False (FAIL)

- **promotion_ready: False**

No chunk_max_tokens promotion is performed by this aggregation. No pipeline_config.json mutation. No runtime default change.
