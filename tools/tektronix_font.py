"""
Relève la police de l'écran Tektronix sur des captures dont on connaît les textes du
panneau, et l'enregistre dans ressources/fonts/tektronix.npz (lue par model/scope.py).

    python tools/tektronix_font.py simple.png zoom.png

Les captures ne sont pas versionnées (fichiers du service) : la table produite, elle, l'est.
Textes attendus : TRUTH, par capture (nom de fichier sans extension) -> {(ligne, colonne)
du mot dans le panneau : texte}. Positions = celles que donne scope.read_panel (bord haut
et gauche de la boîte du mot) ; un mot dont le découpage ne donne pas autant de caractères
que son texte est ignoré.
"""
import pathlib
import sys

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model import labelread, plotimage, scope  # noqa: E402

TRUTH = {
    "simple": {
        (533, 66): "200V/div", (533, 181): "1MΩ", (533, 353): "830.16V",
        (533, 788): "100µs/div", (533, 853): "100MS/s", (533, 938): "10.0ns/pt",
        (557, 66): "5.0v/div", (557, 181): "1MΩ", (557, 353): "-16.0V",
        (578, 66): "50.0V/div", (578, 181): "1MΩ", (578, 353): "-846.16V",
        (578, 798): "acqs", (599, 66): "5.0a/div", (599, 181): "1MΩ", (599, 787): "Auto",
        (642, 144): "Value", (642, 220): "Mean", (642, 300): "Min", (642, 369): "Max",
        (642, 498): "Count", (642, 553): "Info",
        (659, 68): "High", (659, 128): "11.6a", (659, 198): "11.6", (659, 278): "11.6",
        (659, 348): "11.6", (659, 418): "0.0", (659, 488): "1.0",
        (678, 68): "Max", (678, 128): "19.2v", (678, 198): "19.2", (678, 278): "19.2",
        (678, 348): "19.2", (678, 418): "0.0", (678, 488): "1.0",
        (697, 68): "Max", (697, 128): "370.0V", (697, 198): "370.0", (697, 278): "370.0",
        (697, 348): "370.0", (697, 418): "0.0", (697, 488): "1.0",
    },
    "zoom": {
        (513, 396): "10.0µs", (513, 446): "-38.0µs", (513, 496): "62.0µs",
        (537, 346): "5.0v", (537, 396): "10.0µs", (537, 446): "-38.0µs", (537, 496): "62.0µs",
        (558, 346): "50.0V", (558, 396): "10.0µs", (558, 446): "-38.0µs",
        (558, 496): "62.0µs", (579, 346): "5.0a", (579, 396): "10.0µs",
        (579, 446): "-38.0µs", (579, 496): "62.0µs",
        (639, 658): "-16.0V", (658, 658): "-846.16V", (620, 658): "830.16V",
    },
    "zoom3": {
        (513, 181): "1MΩ", (513, 396): "11.1µs", (513, 446): "-36.0µs", (513, 496): "75.2µs",
        (513, 788): "100µs/div", (513, 853): "100MS/s", (513, 938): "10.0ns/pt",
        (537, 66): "200v/div", (537, 181): "1MΩ", (537, 345): "200v", (537, 396): "11.1µs",
        (537, 446): "-36.0µs", (537, 496): "75.2µs",
        (558, 66): "200V/div", (558, 181): "1MΩ", (558, 345): "200V", (558, 396): "11.1µs",
        (558, 446): "-36.0µs", (558, 496): "75.2µs", (558, 798): "acqs",
        (579, 66): "20.0A/div", (579, 181): "50Ω", (579, 345): "20.0A", (579, 396): "11.1µs",
        (579, 446): "-36.0µs", (579, 496): "75.2µs", (579, 787): "Auto",
        (620, 144): "Value", (620, 220): "Mean", (620, 300): "Min", (620, 369): "Max",
        (620, 498): "Count", (620, 553): "Info", (620, 658): "0.0V", (620, 788): "-1.211µs",
        (639, 68): "High", (639, 128): "15.2A", (639, 198): "15.2", (639, 278): "15.2",
        (639, 348): "15.2", (639, 418): "0.0", (639, 488): "1.0", (639, 658): "824V",
        (639, 788): "15.044µs", (662, 658): "824V", (662, 788): "16.256µs",
        (683, 658): "50.69MV/s",
    },
    "zoom4": {
        (513, 181): "1MΩ", (513, 396): "1.0µs", (513, 446): "-2.2µs", (513, 496): "7.8µs",
        (513, 788): "50.0µs/div500MS/s", (513, 937): "2.0ns/pt",
        (537, 66): "200v/div", (537, 181): "1MΩ", (537, 345): "200v", (537, 396): "1.0µs",
        (537, 446): "-2.2µs", (537, 496): "7.8µs",
        (558, 66): "200V/div", (558, 181): "1MΩ", (558, 345): "200V", (558, 396): "1.0µs",
        (558, 446): "-2.2µs", (558, 496): "7.8µs", (558, 798): "acqs",
        (579, 66): "10.0V/div", (579, 181): "1MΩ", (579, 346): "10.0V", (579, 396): "1.0µs",
        (579, 446): "-2.2µs", (579, 496): "7.8µs", (579, 787): "Auto",
        (620, 144): "Value", (620, 220): "Mean", (620, 300): "Min", (620, 369): "Max",
        (620, 498): "Count", (620, 553): "Info", (620, 658): "16.0V", (620, 788): "-250ns",
        (639, 68): "High", (639, 128): "11.2V", (639, 198): "11.2", (639, 278): "11.2",
        (639, 348): "11.2", (639, 418): "0.0", (639, 488): "1.0", (639, 658): "1.08kV",
        (639, 788): "1.85µs",
        (658, 68): "Max", (658, 128): "360.0v", (658, 198): "360.00001", (658, 278): "360.0",
        (658, 348): "360.0", (658, 418): "0.0", (658, 488): "1.0", (658, 658): "1.064kV",
        (658, 788): "2.1µs",
        (677, 68): "Max", (677, 128): "728.0V", (677, 198): "728.00001", (677, 278): "728.0",
        (677, 348): "728.0", (677, 418): "0.0", (677, 488): "1.0", (677, 658): "506.667MV/s",
    },
    "simple7": {
        (643, 181): "1MΩ", (643, 353): "1.008kV", (643, 483): "32.52µs",
        (643, 787): "20.0µs/div100MS/s", (643, 938): "10.0ns/pt",
        (667, 66): "200v/div", (667, 181): "1MΩ", (667, 353): "560V", (667, 482): "42.56µs",
        (688, 66): "200V/div", (688, 181): "1MΩ", (688, 353): "-448V", (688, 483): "10.04µs",
        (709, 66): "10.0A/div", (709, 181): "50Ω", (709, 353): "-44.622MV/s",
        (709, 483): "99.602kHz", (709, 787): "Auto",
    },
    "simple8": {
        (643, 181): "1MΩ", (643, 787): "20.0µs/div100MS/s", (643, 938): "10.0ns/pt",
        (667, 66): "200v/div", (667, 181): "1MΩ", (688, 66): "200V/div", (688, 181): "1MΩ",
        (709, 66): "10.0A/div", (709, 181): "50Ω", (709, 787): "Auto",
    },
}


class _Boxes:
    """Lecteur factice : garde les boîtes de mots de scope.read_panel."""

    def __init__(self):
        self.boxes = []

    def read(self, box):
        self.boxes.append(box)
        return None


def harvest(paths) -> dict:
    samples = {}
    for path in paths:
        name = pathlib.Path(path).stem
        truth = TRUTH.get(name, {})
        rgb = np.asarray(Image.open(path).convert("RGB"))
        top = scope.screen_box(rgb)[3] + 2
        collector = _Boxes()
        scope.read_panel(rgb, top, collector)
        reader = labelread.Reader(255 - scope.panel_gray(rgb, top), scope.VOCABULARY, [])
        for box in collector.boxes:
            text = truth.get((box[1], box[0]))
            if text is None:
                continue
            glyphs = [g for g in reader.glyphs(box) if g.shape == "tall"]
            chars = [c for c in text if c not in labelread.SHAPES]
            if len(glyphs) != len(chars):
                print(f"{name} {box[:2]} « {text} » : {len(glyphs)} caractères pour "
                      f"{len(chars)}, ignoré")
                continue
            for c, g in zip(chars, glyphs):
                samples.setdefault(c, []).append(g)
    return samples


KEEP = 6            # modèles gardés par caractère (fonds noir et gris de la table)


def distinct(glyphs) -> list:
    """Échantillons nettement différents les uns des autres (au plus KEEP)."""
    kept = []
    for g in glyphs:
        if all(np.abs(g.ink - k.ink).mean() > 0.02 for k in kept):
            kept.append(g)
        if len(kept) == KEEP:
            break
    return kept


def main(paths):
    samples = {c: distinct(gs) for c, gs in harvest(paths).items()}
    names = [c for c in sorted(samples) for _ in samples[c]]
    inks = np.array([g.ink for c in sorted(samples) for g in samples[c]])
    ratios = np.array([g.ratio for c in sorted(samples) for g in samples[c]])
    heights = np.array([g.height for c in sorted(samples) for g in samples[c]])
    out = ROOT / "ressources" / "fonts" / "tektronix.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, names=np.array(names), inks=inks, ratios=ratios, heights=heights,
                        glyph=np.array(plotimage.GLYPH))
    print(f"{len(samples)} caractères, {len(names)} modèles -> {out}")
    print({c: len(samples[c]) for c in names})


if __name__ == "__main__":
    main(sys.argv[1:])
