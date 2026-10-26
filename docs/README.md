# docs

`architecture.svg` is the module diagram used as Figure 1 of the SoftwareX
article. It is drawn by hand, so it is kept here as a source file rather than
under the generated figures.

Whenever the module graph changes, re-run:

    python scripts/check_architecture_figure.py

It reads the arrows out of the SVG and the imports out of `src/calrcpsp`, and
fails if an arrow points at the wrong module, a real dependency has no arrow,
or a connector crosses a box it does not belong to.
