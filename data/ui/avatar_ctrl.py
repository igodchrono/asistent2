# ui/avatar_ctrl.py — только применение анимации, без выбора эмоции за модель
from __future__ import annotations

import re
from typing import Optional

import config


LOOP_EMOTIONS = {
    "idle", "idle_sad", "idle_happy", "idle_angry", "idle_sly",
    "dance", "dance_happy", "dance_sly", "dance_love",
    "searching", "searching_happy", "searching_sad", "searching_angry",
    "undress", "undress_happy", "undress_sly", "undress_love",
    "undress_playful", "undress_seductive", "undress_teasing",
    "undress_mischievous", "undress_shy",
    "bath", "bath_shy", "bath_happy",
    "bed", "bed_love", "bed_shy",
}
ONESHOT_EMOTIONS = {
    "happy_big", "surprised", "surprised_happy", "surprised_shocked",
    "shocked", "scared", "cry", "cry_sad", "cry_angry",
    "angry_frustrated", "proud", "proud_happy",
    "pointing", "pointing_happy", "pointing_angry", "pointing_love",
    "flirty", "flirty_happy", "teasing", "teasing_sly",
    "seductive", "seductive_happy",
    "mischievous", "mischievous_happy",
}


class AvatarController:
    def __init__(self, window, avatar_window, analyzer=None):
        self.window = window
        self.avatar_window = avatar_window
        self.analyzer = analyzer
        self.current_base_anim = "neutral"

    def extract_animation(self, text: str) -> Optional[str]:
        if not text:
            return None
        match = re.search(r"\[ANIM:(\w+)\]", text, re.IGNORECASE)
        if not match:
            return None
        anim = match.group(1).lower()
        is_nsfw = anim in getattr(config, "NSFW_EMOTIONS", [])
        if is_nsfw and not getattr(config, "NSFW_ENABLED", True):
            print("🔞 NSFW отключено → neutral")
            return "neutral"
        enabled = getattr(config, "ENABLED_EMOTIONS", None)
        if enabled is not None:
            if anim in enabled:
                return anim
            if "_" in anim:
                base = anim.split("_")[0]
                if base in enabled:
                    return base
            for e in enabled:
                if anim.startswith(e) or e.startswith(anim):
                    return e
            return "neutral"
        return anim

    def update(self, anim_name, force_static=False, force_sprite=False):
        if not self.avatar_window:
            return

        anim_name = (anim_name or "neutral").lower().strip()
        print(f"🎬 update_avatar_animation: {anim_name} (static={force_static}, sprite={force_sprite})")

        is_nsfw = False
        if self.analyzer:
            if hasattr(self.analyzer, "is_nsfw_emotion"):
                is_nsfw = self.analyzer.is_nsfw_emotion(anim_name)
            else:
                is_nsfw = anim_name in getattr(config, "NSFW_EMOTIONS", [])
        if not is_nsfw:
            _nsfw_set = getattr(config, "NSFW_EMOTIONS", []) or []
            is_nsfw = anim_name in _nsfw_set or any(anim_name.startswith(b + "_") for b in _nsfw_set)
        if is_nsfw and not getattr(config, "NSFW_ENABLED", True):
            print("🔞 NSFW отключено → neutral")
            anim_name = "neutral"
            is_nsfw = False

        enabled_emotions = getattr(config, "ENABLED_EMOTIONS", None)
        if enabled_emotions is not None and anim_name not in enabled_emotions:
            found = False
            for emotion in enabled_emotions:
                if anim_name.startswith(emotion) or emotion.startswith(anim_name):
                    anim_name = emotion
                    found = True
                    break
            if not found:
                print(f"⚠️ {anim_name} нет в ENABLED_EMOTIONS → neutral")
                anim_name = "neutral"

        if not self.avatar_window.animations and not self.avatar_window.static_frames:
            self.avatar_window.load_all_animations()

        has_sprite = (
            anim_name in self.avatar_window.animations
            and len(self.avatar_window.animations[anim_name]) > 1
        )
        has_static = anim_name in self.avatar_window.static_frames

        prefer_static = (
            force_static
            or anim_name not in LOOP_EMOTIONS and anim_name not in ONESHOT_EMOTIONS
        )
        prefer_loop = anim_name in LOOP_EMOTIONS
        prefer_oneshot = anim_name in ONESHOT_EMOTIONS
        if force_sprite:
            prefer_static = False

        print(
            f"   has_sprite={has_sprite}, has_static={has_static}, "
            f"prefer_static={prefer_static}, loop={prefer_loop}, oneshot={prefer_oneshot}"
        )

        if has_sprite and not prefer_static:
            loop = prefer_loop and not prefer_oneshot
            ok = self.avatar_window.play_animation(anim_name, loop=loop)
            if ok:
                mode = "loop" if loop else "oneshot"
                print(f"▶️ Спрайт [{mode}]: {anim_name}")
            else:
                print(f"🖼️ Статика (спрайт не стартовал): {anim_name}")
        elif has_static:
            self.avatar_window.show_static(anim_name)
            print(f"🖼️ Статика: {anim_name}")
        else:
            fallback = None
            statics = self.avatar_window.static_frames
            anims = self.avatar_window.animations

            def _has(name: str) -> bool:
                return name in statics or name in anims

            if not fallback:
                prefix = anim_name + "_"
                for pool in (statics, anims):
                    hits = [k for k in pool.keys() if k == anim_name or k.startswith(prefix)]
                    if hits:
                        prefer = [h for h in hits if h.endswith("_sad") or h.endswith("_happy") or h.endswith("_shy")]
                        fallback = (prefer or hits)[0]
                        break
            if "_" in anim_name:
                base = anim_name.split("_")[0]
                if not fallback and _has(base):
                    fallback = base
            if not fallback and is_nsfw and hasattr(self.analyzer, "get_static_fallback"):
                fb = self.analyzer.get_static_fallback(anim_name)
                if fb and _has(fb):
                    fallback = fb
            if not fallback and is_nsfw:
                for cand in ("undress", "undress_sly", "undress_love", "teasing", "playful", "sly"):
                    if _has(cand):
                        fallback = cand
                        break
            if not fallback:
                fallback = "neutral"

            if fallback in anims and len(anims.get(fallback) or []) > 1:
                self.avatar_window.play_animation(fallback, loop=False)
                print(f"▶️ Спрайт fallback: {fallback}")
            elif fallback in statics:
                self.avatar_window.show_static(fallback)
                print(f"🖼️ Статика fallback: {fallback}")
            else:
                self.avatar_window.show_static("neutral")
                print("🖼️ Fallback: neutral")

        if anim_name != "thinking":
            self.current_base_anim = anim_name

    def reload(self):
        if self.avatar_window:
            self.avatar_window.load_all_animations()
            self.update(self.current_base_anim)
