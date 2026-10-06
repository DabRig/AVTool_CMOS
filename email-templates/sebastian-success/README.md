# Sebastian Success email template

Deep-space version of the Smooth Scaling "from the desk of" email: a twinkling
starfield banner with the Sebastian Success logo, a starlight divider, and a
handwritten-style signature.

- `build.py` renders `out/hero.gif`, `out/divider.gif` and `out/sig.png`.
  Pass a new banner script line to change the greeting/date:
  `python3 build.py "Grand Rising, brother · October 7, 2026"`
- `email.html` is the email body, with `{{ASSETS}}` standing in for where the
  images are hosted.
- `make_page.py` turns it into a one-page "copy into Gmail" tool: a live
  preview with the images embedded, and a Copy button that puts the email on
  the clipboard with the images pointing at their public URLs:
  `python3 make_page.py https://raw.githubusercontent.com/DabRig/AVTool_CMOS/<commit>/email-templates/sebastian-success/out page.html`

## Why paste instead of a Gmail API draft

Gmail's connector removes every `<img>`, background image and `<style>` from
drafts it creates, so the banner can't arrive that way. Pasting rich HTML into
Gmail's compose window keeps the images, and Gmail loads them from their public
URLs. The motion lives inside the GIFs because no mail client runs JavaScript
and Gmail strips CSS animation.

Fonts (SIL OFL, downloaded on first run): Cinzel, Cormorant Garamond Italic,
Herr Von Muellerhoff.
