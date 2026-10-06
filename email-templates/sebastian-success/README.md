# Sebastian Success email template

Deep-space version of the Smooth Scaling "from the desk of" email: a twinkling
starfield banner with the Sebastian Success logo, a starlight divider, and a
handwritten-style signature.

- `build.py` renders `out/hero.gif`, `out/divider.gif` and `out/sig.png`.
  Pass a new banner script line to change the greeting/date:
  `python3 build.py "Grand Rising, brother · October 7, 2026"`
- `email.html` is the email body. Its images point at `out/` for local preview;
  before sending, swap `out/` for wherever the images are hosted (for example
  `https://raw.githubusercontent.com/DabRig/AVTool_CMOS/<commit>/email-templates/sebastian-success/out/`).

Fonts (SIL OFL, downloaded on first run): Cinzel, Cormorant Garamond Italic,
Herr Von Muellerhoff.
