"""Local workaround for LibreLane 3.0.14's DEF-template metric bug.

`Odb.ApplyDEFTemplate.run` reads `metrics_updates["design__die__bbox"]` with
no fallback.  The helper script writes that string metric, but this build's
metric parser drops non-numeric metrics, so the key is absent and the step
dies with KeyError('design__die__bbox') *after* it has already relocated the
pins.  Patch the wrapper to treat the metric as optional; the pin relocation
itself is unchanged.

Loaded automatically when this directory is on PYTHONPATH (Python imports
`sitecustomize` at startup), so the flow can be run as:

    PYTHONPATH=$PWD/openlane/dac_video_dig/librelane_patch \
        librelane openlane/dac_video_dig/config.librelane.json ...
"""
from __future__ import annotations

try:
    from decimal import Decimal

    import librelane.steps.odb as _odb
    from librelane.logging import info

    def _run(self, state_in, **kwargs):
        if self.config["FP_DEF_TEMPLATE"] is None:
            info(f"No DEF template provided, skipping '{self.id}'...")
            return {}, {}
        views_updates, metrics_updates = super(
            _odb.ApplyDEFTemplate, self).run(state_in, **kwargs)
        design_area = self.state_in.result().metrics.get("design__die__bbox")
        template_area = metrics_updates.get("design__die__bbox")
        if design_area and template_area:
            a = [Decimal(p) for p in template_area.split()]
            b = [Decimal(p) for p in design_area.split()]
            if a != b:
                self.warn("The die area in FP_DEF_TEMPLATE differs from the "
                          "design die area; pin placement may be incorrect.")
                self.warn(f"Design area: {design_area}. Template: {template_area}")
        elif design_area:
            # The relocation still happened; only the area cross-check is
            # unavailable in this LibreLane build.
            info("DEF template applied; design__die__bbox metric was not "
                 "returned by the helper (area cross-check skipped).")
        return views_updates, {}

    _odb.ApplyDEFTemplate.run = _run
except Exception as exc:  # pragma: no cover - never break the CLI on patch failure
    import sys
    print(f"librelane_patch: not applied: {exc}", file=sys.stderr)
