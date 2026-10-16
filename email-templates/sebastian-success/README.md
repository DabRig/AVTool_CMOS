# Sebastian Success email

Deep-space version of the Smooth Scaling "from the desk of" email: a twinkling
starfield banner with the Sebastian Success logo, starlight dividers, and a
handwritten-style signature.

## Everyday use: the composer page

`make_composer.py` builds a one-page composer. Type the message (one line per
thought, emojis welcome), check the live preview, click **Copy email**, and
paste into Gmail with Cmd+V. The greeting under the banner, sign-off and footer
are editable fields, so the same banner works for every email.

    python3 make_composer.py https://raw.githubusercontent.com/DabRig/AVTool_CMOS/<commit>/email-templates/sebastian-success/out page.html

## Assets

`build.py` renders into `out/`:

- `hero-space.gif`: the evergreen animated banner (no greeting baked in)
- `divider.gif`: the sparkle divider line
- `sig.png`: the signature
- `hero.gif`: optional one-off banner with a greeting baked in:
  `python3 build.py "Let's get 'er done, feller · October 6, 2026"`

Fonts (SIL OFL, downloaded on first run): Cinzel, Cormorant Garamond Italic,
Herr Von Muellerhoff.

## Why paste instead of a Gmail API draft

Gmail's connector removes every `<img>`, background image and `<style>` from
drafts it creates, so the banner can't arrive that way. Pasting rich HTML into
Gmail's compose window keeps the images, and Gmail loads them from their public
URLs. The motion lives inside the GIFs because no mail client runs JavaScript
and Gmail strips CSS animation.
