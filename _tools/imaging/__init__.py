"""Ядро библиотеки картинок (Pillow + numpy, без Qt). Окно и командная строка зовут его как `K`."""

from imaging.cutting import (
    add_outline,
    border_color,
    cells,
    cut,
    find_pieces,
    grid_pieces,
    label,
    object_mask,
    remove_bg,
    sheet_kind,
    to_square,
)
from imaging.doctor import IMPORTED, PROBLEMS, doctor_check, job_doctor
from imaging.editing import (
    ADJ,
    ADJ_RANGE,
    EDITABLE,
    adjust,
    apply_edits,
    brush,
    defringe,
    edit_format,
    encode_edit,
    job_edit,
    recolor,
    round_corners,
    shadow,
)
from imaging.encoding import (
    BEST,
    FITS,
    KINDS,
    MATTES,
    TARGETS,
    auto_quality,
    best_formats,
    clean,
    compress,
    encode,
    flat,
    has_alpha,
    is_art,
    matte_rgb,
    resize,
    save,
    ssim,
    to_svg,
    trim,
)
from imaging.files import (
    EXT,
    INBOX,
    LIB,
    ORIENT,
    fmt_of,
    hex_rgb,
    images_in,
    is_animated,
    load,
    size_of,
    upright,
    write_atomic,
)
from imaging.gallery import build_gallery
from imaging.jobs import RETINA, job_compress, job_export, job_image, job_variant
from imaging.similarity import (
    COLORS,
    SAME_DIFF,
    SAME_RATIO,
    colors,
    main_colors,
    same_sig,
    signature,
)
from imaging.sprites import (
    atlas,
    atlas_files,
    contact_sheet,
    css_id,
    frame_ids,
    icon_set,
    job_svg,
    svg_sprite,
)

__all__ = [n for n in dir() if not n.startswith("_")]
