try:
    from .nodes_galiais_prompt_system import (
        NODE_CLASS_MAPPINGS as _PROMPT_CLS,
        NODE_DISPLAY_NAME_MAPPINGS as _PROMPT_NAMES,
    )
    from .nodes_galiais_character_prompt import (
        NODE_CLASS_MAPPINGS as _CHARACTER_CLS,
        NODE_DISPLAY_NAME_MAPPINGS as _CHARACTER_NAMES,
    )
    from .nodes_galiais_prompt_style import (
        NODE_CLASS_MAPPINGS as _STYLE_CLS,
        NODE_DISPLAY_NAME_MAPPINGS as _STYLE_NAMES,
    )
except ImportError:
    from nodes_galiais_prompt_system import (
        NODE_CLASS_MAPPINGS as _PROMPT_CLS,
        NODE_DISPLAY_NAME_MAPPINGS as _PROMPT_NAMES,
    )
    from nodes_galiais_character_prompt import (
        NODE_CLASS_MAPPINGS as _CHARACTER_CLS,
        NODE_DISPLAY_NAME_MAPPINGS as _CHARACTER_NAMES,
    )
    from nodes_galiais_prompt_style import (
        NODE_CLASS_MAPPINGS as _STYLE_CLS,
        NODE_DISPLAY_NAME_MAPPINGS as _STYLE_NAMES,
    )

NODE_CLASS_MAPPINGS = {
    **_PROMPT_CLS,
    **_CHARACTER_CLS,
    **_STYLE_CLS,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    **_PROMPT_NAMES,
    **_CHARACTER_NAMES,
    **_STYLE_NAMES,
}

WEB_DIRECTORY = "./web/js"
__version__ = "1.0.1"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
    "__version__",
]
