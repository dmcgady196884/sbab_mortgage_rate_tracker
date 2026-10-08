"""
Unit tests for the README's stable heatmap: the current surface is also written under a
fixed name (the dated filenames change on every structural change), and the email does
not attach that copy a second time. No network; files live in tmp_path.

Run: pytest tests/test_visualizations.py -v
"""
from importlib import import_module

import matplotlib
matplotlib.use('Agg')  # no display needed
import pandas as pd

from io_contracts import CURRENT_DISCOUNT_SURFACE_PNG

viz = import_module('create_price_visualizations')
step_8 = import_module('8_send_email_with_report')

SURFACE = pd.DataFrame([[0.10, 0.20], [0.30, 0.40]],
                       index=['(0-1)M', '(1+)M'], columns=['(0-50)%', '(50+)%'])


def test_current_surface_also_gets_a_stable_named_copy(tmp_path):
    dated = viz.generate_discount_surface_plot(SURFACE, '2026-09-25', 'current', tmp_path, maturities=[3, 12])
    stable = tmp_path / CURRENT_DISCOUNT_SURFACE_PNG
    assert stable.exists()
    assert stable.read_bytes() == dated.read_bytes()


def test_closed_surface_gets_no_stable_copy(tmp_path):
    viz.generate_discount_surface_plot(SURFACE, '2026-03-31', '2026-09-24', tmp_path, maturities=[3, 12])
    assert not (tmp_path / CURRENT_DISCOUNT_SURFACE_PNG).exists()


def test_email_does_not_attach_the_stable_copy_twice(tmp_path):
    for name in ['discount_surface_from_20260925_to_current_for_3_12_months.png', CURRENT_DISCOUNT_SURFACE_PNG]:
        (tmp_path / name).write_bytes(b'png')
    names = [p.name for p in step_8._collect_all_visualizations(tmp_path)]
    assert names == ['discount_surface_from_20260925_to_current_for_3_12_months.png']
