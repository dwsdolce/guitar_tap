# @parity test/field-precision
"""Mirror of Swift ``FieldPrecisionTests`` / web ``field-precision.test.ts``.

Pins the numeric-precision single source of truth (``field_precision``): the per-field decimal
table, the restrict-on-entry predicate (``decimals_within``), half-away-from-zero rounding
(``rounded``), and display formatting (``string``). Keep these cases identical across the three
editions so the table, regex, and rounding can never quietly drift apart.
"""
from models import field_precision as fp


# --- Precision table ---

def test_table_matches_canonical_values():
    assert fp.LINEAR_DIMENSION_MM == 2
    assert fp.MASS_G == 1
    assert fp.BODY_DIMENSION_MM == 0
    assert fp.FREQUENCY_HZ == 0
    assert fp.MAGNITUDE_DB == 0
    assert fp.STIFFNESS == 0
    assert fp.PEAK_FREQUENCY_HZ == 1
    assert fp.PEAK_MAGNITUDE_DB == 1
    assert fp.Q_FACTOR == 1
    assert fp.YOUNGS_MODULUS_GPA == 2
    assert fp.SPEED_OF_SOUND_MS == 0
    assert fp.DENSITY_G_PER_CM3 == 3
    assert fp.DECAY_RATIO == 2


# --- decimals_within (restrict-on-entry predicate) ---

def test_decimals_within_accepts_within_precision():
    assert fp.decimals_within("29.35", 2)
    assert fp.decimals_within("29.3", 2)
    assert fp.decimals_within("29", 2)


def test_decimals_within_rejects_over_precision():
    assert not fp.decimals_within("29.356", 2)
    assert not fp.decimals_within("29.35", 1)


def test_decimals_within_accepts_trailing_dot_while_typing():
    assert fp.decimals_within("29.", 2)


def test_decimals_within_rejects_dot_at_zero_decimals():
    assert not fp.decimals_within("495.", 0)
    assert not fp.decimals_within("495.5", 0)
    assert fp.decimals_within("495", 0)


def test_decimals_within_accepts_in_progress_empty_and_minus():
    assert fp.decimals_within("", 2)
    assert fp.decimals_within("-", 2)
    assert fp.decimals_within("", 0)
    assert fp.decimals_within("-", 0)


def test_decimals_within_accepts_negative():
    assert fp.decimals_within("-45", 0)
    assert fp.decimals_within("-45.5", 1)
    assert not fp.decimals_within("-45.55", 1)


def test_decimals_within_rejects_non_numeric():
    assert not fp.decimals_within("4a", 0)
    assert not fp.decimals_within("abc", 2)
    assert not fp.decimals_within("2..5", 2)


# --- rounded (half away from zero) ---

def test_rounded_half_away_from_zero():
    assert fp.rounded(2.5, 0) == 3
    assert fp.rounded(0.5, 0) == 1
    assert fp.rounded(-2.5, 0) == -3
    assert fp.rounded(-0.5, 0) == -1


def test_rounded_rounds_to_precision():
    assert abs(fp.rounded(29.356, 2) - 29.36) < 0.001
    assert abs(fp.rounded(29.354, 2) - 29.35) < 0.001
    assert abs(fp.rounded(29.35, 2) - 29.35) < 0.001


def test_rounded_negative_rounds_away_from_zero():
    assert abs(fp.rounded(-29.356, 2) - (-29.36)) < 0.001


# --- string (display formatting) ---

def test_string_formats_at_precision():
    assert fp.string(29.4, 2) == "29.40"
    assert fp.string(29, 0) == "29"
    assert fp.string(-100, 0) == "-100"
    assert fp.string(2.5, 1) == "2.5"


def test_string_rounds_for_display():
    assert fp.string(2.678, 2) == "2.68"
