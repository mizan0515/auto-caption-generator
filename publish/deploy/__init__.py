"""Deploy scaffolding helpers for the auto-caption-generator static site.

This package collects pre-deploy verification utilities that are safe to run
locally before pushing site/ to a free static host (Cloudflare Pages primary,
GitHub Pages fallback).

Public entry points:
    publish.deploy.check    — preflight (structure + cookie leak scan).
    publish.deploy.package  — bundle site/ into per-target deploy archives
                              (Cloudflare Pages zip, GitHub Pages tar.gz);
                              preflight gating refuses to write archives if
                              errors are present.
"""
