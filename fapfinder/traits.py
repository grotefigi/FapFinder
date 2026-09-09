from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Trait:
    key: str
    label: str
    options: tuple[tuple[str, str], ...]
    note: str = ""
    automatic: bool = True


TRAITS = (
    Trait("hair_color", "Hair color", (("black", "Black"), ("brown", "Brown"), ("blonde", "Blonde"), ("red", "Red / auburn"), ("gray", "Gray / white"), ("colorful", "Dyed / colorful")), "Lighting and dyed hair can affect estimates."),
    Trait("hair_length", "Hair length", (("short", "Short"), ("medium", "Shoulder length"), ("long", "Long"), ("bald", "Shaved / bald"))),
    Trait("hair_texture", "Hair texture", (("straight", "Straight"), ("wavy", "Wavy"), ("curly", "Curly"), ("coily", "Coily"))),
    Trait("build", "Body build · apparent", (("slim", "Slim / skinny"), ("average", "Average"), ("curvy", "Curvy"), ("plus_size", "Plus-size"), ("muscular", "Muscular")), "A visual description, affected by clothes and pose. Not a health assessment."),
    Trait("skin_tone", "Skin tone · visible", (("light", "Light"), ("medium", "Medium"), ("tan", "Tan"), ("deep", "Deep")), "Describes visible color under this lighting, not race or ethnicity."),
    Trait("age", "Age range · apparent", (("18_29", "18–29"), ("30_44", "30–44"), ("45_59", "45–59"), ("60_plus", "60+")), "An unreliable appearance estimate, never age verification. Unknown is the default until reviewed."),
    Trait("face_shape", "Face shape", (("oval", "Oval"), ("round", "Round"), ("square", "Square"), ("heart", "Heart-shaped"), ("long", "Long / oblong")), "Perspective and occlusion can change the appearance."),
    Trait("framing", "Framing", (("portrait", "Portrait / close-up"), ("upper_body", "Upper body"), ("full_body", "Full body"))),
    Trait("glasses", "Glasses", (("yes", "Glasses"), ("no", "No glasses"))),
    Trait("setting", "Setting", (("studio", "Studio"), ("indoors", "Indoors"), ("outdoors", "Outdoors"))),
    Trait("height", "Height · manual", (("under_160", "Under 160 cm"), ("160_169", "160–169 cm"), ("170_179", "170–179 cm"), ("180_plus", "180+ cm")), "Actual height needs a known measurement; it cannot be recovered reliably from an uncalibrated photo.", False),
)
BY_KEY = {trait.key: trait for trait in TRAITS}
VALID_TAGS = {(trait.key, key) for trait in TRAITS for key, _ in trait.options} | {(trait.key, "unknown") for trait in TRAITS}

DESCRIPTIONS = {
    "hair_color": ["black hair", "brown hair", "blonde hair", "red or auburn hair", "gray or white hair", "brightly colored dyed hair"],
    "hair_length": ["short hair", "shoulder-length hair", "long hair", "a shaved or bald head"],
    "hair_texture": ["straight hair", "wavy hair", "curly hair", "coily hair"],
    "build": ["a slim build", "an average build", "a curvy build", "a plus-size build", "a muscular build"],
    "skin_tone": ["light visible skin", "medium-toned visible skin", "tan visible skin", "deep-toned visible skin"],
    "age": ["the appearance of an adult in their twenties", "the appearance of an adult aged thirty to forty-four", "the appearance of an adult aged forty-five to fifty-nine", "the appearance of an adult over sixty"],
    "face_shape": ["an oval face", "a round face", "a square face", "a heart-shaped face", "a long oblong face"],
    "framing": ["portrait framing showing only the face", "upper-body framing", "full-body framing showing head to feet"],
    "glasses": ["eyeglasses", "no eyeglasses"],
    "setting": ["a studio background", "an indoor background", "an outdoor background"],
}


def label_for(group, value):
    return dict(BY_KEY[group].options).get(value, "Unknown / not visible")


def prompt_groups():
    result = {}
    for trait in TRAITS:
        if not trait.automatic:
            continue
        options = []
        for (value, _), description in zip(trait.options, DESCRIPTIONS[trait.key]):
            options.append((value, [f"a photo of a person with {description}.", f"a photograph showing a person with {description}."]))
        unknown = {
            "age": "a person whose age cannot be determined, possibly not an adult",
            "build": "a person whose body build is hidden by clothing or out of the frame",
            "face_shape": "a person whose face is not clearly visible",
            "skin_tone": "a person whose skin is hidden or affected by colored lighting",
        }.get(trait.key, f"a photo where the person's {trait.label.lower()} cannot be determined")
        options.append(("unknown", [f"a photo of {unknown}.", f"a photograph showing {unknown}."]))
        result[trait.key] = options
    return result
