# Test fixtures

The six JSON files in this folder are instances from the published CA-RCPSP
benchmark dataset. They are copied here unchanged so that the test suite and
continuous integration can run without downloading anything.

Source: M. A. Uddin, J. Gaber, P. Petitjean, F. Cortinovis, "An expert-informed
multi-scale synthetic benchmark dataset for calendar-aware resource-constrained
project scheduling (CA-RCPSP)", Data in Brief 69 (2026) 113256.
doi:10.1016/j.dib.2026.113256

Data archive: https://doi.org/10.5281/zenodo.20553817
Licence: CC BY 4.0. Reused here with attribution.

The full dataset holds twelve instances across four scale tiers. The six here
are the tiny and small tiers. Point the test suite at the full deposit with:

    CALRCPSP_DATASET=/path/to/carm-plus-dataset/data/scenarios pytest
