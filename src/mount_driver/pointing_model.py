"""Pointing model correction for polar misalignment.

Implements a 2-parameter (ME/MA) pointing model that corrects for the
known polar alignment error of roughly-aligned equatorial mounts.

ME (Meridian Error): azimuth offset of mount's pole from true pole (radians)
MA (Altitude Error): altitude offset of mount's pole from true pole (radians)

The model predicts the mount error (actual - commanded):
    HA = (LST - RA) * 15  (degrees)
    delta_HA  = ME * cos(HA) * tan(DEC) - MA * sin(HA) * tan(DEC)
    delta_DEC = ME * sin(HA) + MA * cos(HA)

Pre-compensation applied to target coordinates before sending to mount:
    corrected_RA  = RA + delta_HA / 15  (hours)
    corrected_DEC = DEC - delta_DEC  (degrees)
"""

import math
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class PointingModel:
    """2-parameter pointing model for polar misalignment correction.

    Attributes:
        me: Meridian Error - azimuth offset of pole (radians)
        ma: Altitude Error - altitude offset of pole (radians)
    """
    me: float = 0.0
    ma: float = 0.0

    def to_dict(self) -> dict:
        return {'me': self.me, 'ma': self.ma}

    @classmethod
    def from_dict(cls, d: dict) -> 'PointingModel':
        return cls(me=d.get('me', 0.0), ma=d.get('ma', 0.0))

    def is_zero(self) -> bool:
        return abs(self.me) < 1e-10 and abs(self.ma) < 1e-10


@dataclass
class CalibrationPoint:
    """A single calibration measurement.

    Attributes:
        commanded_ra: RA sent to mount (hours)
        commanded_dec: DEC sent to mount (degrees)
        actual_ra: RA corresponding to where mount actually pointed (hours)
        actual_dec: DEC corresponding to where mount actually pointed (degrees)
        lst: Local sidereal time at measurement (hours)
    """
    commanded_ra: float
    commanded_dec: float
    actual_ra: float
    actual_dec: float
    lst: float


# Clamp threshold for tan(DEC) near poles
_TAN_DEC_MAX = 50.0  # ~88.8 degrees


def compute_correction(ra: float, dec: float, lst: float,
                       model: PointingModel) -> Tuple[float, float]:
    """Apply pointing model correction to target RA/DEC.

    Args:
        ra: Target RA in hours (0-24)
        dec: Target DEC in degrees (-90 to 90)
        lst: Local sidereal time in hours
        model: Pointing model parameters

    Returns:
        (corrected_ra, corrected_dec) - corrected coordinates to send to mount
    """
    if model.is_zero():
        return ra, dec

    # Hour angle in degrees
    ha_deg = (lst - ra) * 15.0
    ha_rad = math.radians(ha_deg)
    dec_rad = math.radians(dec)

    # Clamp tan(DEC) to avoid singularity near poles
    tan_dec = math.tan(dec_rad)
    tan_dec = max(-_TAN_DEC_MAX, min(_TAN_DEC_MAX, tan_dec))

    cos_ha = math.cos(ha_rad)
    sin_ha = math.sin(ha_rad)

    # Corrections in degrees
    delta_ha_deg = model.me * cos_ha * tan_dec - model.ma * sin_ha * tan_dec
    delta_dec_deg = model.me * sin_ha + model.ma * cos_ha

    # Convert ME/MA from radians to degrees for the correction
    delta_ha_deg = math.degrees(delta_ha_deg)
    delta_dec_deg = math.degrees(delta_dec_deg)

    # Apply corrections: pre-compensate for the predicted error
    # Model predicts actual = commanded + error, so command = target - error
    # For RA: HA = (LST-RA)*15, so subtracting from HA means adding to RA
    corrected_ra = ra + delta_ha_deg / 15.0
    corrected_dec = dec - delta_dec_deg

    # Normalize RA to 0-24
    while corrected_ra < 0:
        corrected_ra += 24.0
    while corrected_ra >= 24.0:
        corrected_ra -= 24.0

    # Clamp DEC to valid range
    corrected_dec = max(-90.0, min(90.0, corrected_dec))

    return corrected_ra, corrected_dec


def solve_pointing_model(points: List[CalibrationPoint]) -> Tuple[PointingModel, float]:
    """Solve for ME/MA from calibration measurements using least-squares.

    Sets up the linear system from the pointing model equations:
        delta_HA  = ME * cos(HA) * tan(DEC) - MA * sin(HA) * tan(DEC)
        delta_DEC = ME * sin(HA) + MA * cos(HA)

    Each calibration point contributes two equations (one for HA, one for DEC).

    Args:
        points: List of calibration measurements (minimum 2 required)

    Returns:
        (model, rms_error) - solved pointing model and RMS residual in degrees
    """
    if len(points) < 2:
        raise ValueError('Need at least 2 calibration points to solve model')

    # Build the linear system: A * [ME, MA]^T = b
    # Each point gives 2 equations (HA and DEC corrections)
    # We solve via normal equations: (A^T A) x = A^T b

    ata_00 = 0.0  # A^T A [0,0]
    ata_01 = 0.0  # A^T A [0,1]
    ata_11 = 0.0  # A^T A [1,1]
    atb_0 = 0.0   # A^T b [0]
    atb_1 = 0.0   # A^T b [1]

    for pt in points:
        # Observed error: actual - commanded
        # Model predicts: actual = commanded + ME*f(HA,DEC) + MA*g(HA,DEC)
        ha_cmd_deg = (pt.lst - pt.commanded_ra) * 15.0
        ha_act_deg = (pt.lst - pt.actual_ra) * 15.0

        delta_ha_deg = ha_act_deg - ha_cmd_deg
        # Normalize to -180..180 for RA wrap-around
        if delta_ha_deg > 180:
            delta_ha_deg -= 360
        elif delta_ha_deg < -180:
            delta_ha_deg += 360
        delta_dec_deg = pt.actual_dec - pt.commanded_dec

        # Use the commanded position for the model coefficients
        ha_rad = math.radians(ha_cmd_deg)
        dec_rad = math.radians(pt.commanded_dec)

        cos_ha = math.cos(ha_rad)
        sin_ha = math.sin(ha_rad)
        tan_dec = math.tan(dec_rad)
        tan_dec = max(-_TAN_DEC_MAX, min(_TAN_DEC_MAX, tan_dec))

        # HA equation: delta_HA = ME * cos(HA) * tan(DEC) - MA * sin(HA) * tan(DEC)
        # Coefficients for [ME, MA]: [cos(HA)*tan(DEC), -sin(HA)*tan(DEC)]
        a_ha_me = cos_ha * tan_dec
        a_ha_ma = -sin_ha * tan_dec
        # Convert delta_ha from degrees to radians for consistent units with ME/MA
        b_ha = math.radians(delta_ha_deg)

        # DEC equation: delta_DEC = ME * sin(HA) + MA * cos(HA)
        # Coefficients for [ME, MA]: [sin(HA), cos(HA)]
        a_dec_me = sin_ha
        a_dec_ma = cos_ha
        b_dec = math.radians(delta_dec_deg)

        # Accumulate normal equations
        ata_00 += a_ha_me * a_ha_me + a_dec_me * a_dec_me
        ata_01 += a_ha_me * a_ha_ma + a_dec_me * a_dec_ma
        ata_11 += a_ha_ma * a_ha_ma + a_dec_ma * a_dec_ma
        atb_0 += a_ha_me * b_ha + a_dec_me * b_dec
        atb_1 += a_ha_ma * b_ha + a_dec_ma * b_dec

    # Solve 2x2 system: [ata_00, ata_01; ata_01, ata_11] * [ME; MA] = [atb_0; atb_1]
    det = ata_00 * ata_11 - ata_01 * ata_01
    if abs(det) < 1e-20:
        raise ValueError('Singular matrix - calibration points may be too close together')

    me = (ata_11 * atb_0 - ata_01 * atb_1) / det
    ma = (ata_00 * atb_1 - ata_01 * atb_0) / det

    model = PointingModel(me=me, ma=ma)

    # Calculate RMS residual: how well model predicts the observed errors
    sum_sq = 0.0
    for pt in points:
        ha_deg = (pt.lst - pt.commanded_ra) * 15.0
        ha_rad = math.radians(ha_deg)
        dec_rad = math.radians(pt.commanded_dec)
        tan_dec = math.tan(dec_rad)
        tan_dec = max(-_TAN_DEC_MAX, min(_TAN_DEC_MAX, tan_dec))

        # Model-predicted error
        pred_delta_ha_deg = math.degrees(
            model.me * math.cos(ha_rad) * tan_dec - model.ma * math.sin(ha_rad) * tan_dec
        )
        pred_delta_dec_deg = math.degrees(
            model.me * math.sin(ha_rad) + model.ma * math.cos(ha_rad)
        )

        # Predicted actual position
        # actual_HA = cmd_HA + delta_HA, so actual_RA = cmd_RA - delta_HA/15
        pred_actual_ra = pt.commanded_ra - pred_delta_ha_deg / 15.0
        pred_actual_dec = pt.commanded_dec + pred_delta_dec_deg

        # Residual: predicted actual vs measured actual
        ra_err_deg = (pred_actual_ra - pt.actual_ra) * 15.0
        if ra_err_deg > 180:
            ra_err_deg -= 360
        elif ra_err_deg < -180:
            ra_err_deg += 360
        dec_err_deg = pred_actual_dec - pt.actual_dec
        sum_sq += ra_err_deg ** 2 + dec_err_deg ** 2

    rms = math.sqrt(sum_sq / (2 * len(points)))

    return model, rms
