"""Renders the mod's art with Chromium (Playwright): Anton + Barlow Condensed, Helldivers yellow on black,
the actual warning sound drawn as a waveform over a charge meter that reaches full damage exactly where the first
warning beep starts (the cue from ../assets/warning.json); the beeps are drawn as red blocks after it.
Outputs ../art/: thumbnail_1254.png, thumbnail_512.png (Arsenal), header_1300x372.png, gallery_1920x1080.png,
GitHub-Social-1280x640.png (the repo's social preview), options/*.png (Arsenal option icons)."""
import base64, json, os, wave
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ART = os.path.join(ROOT, 'art')
BADGE = '3.0'
RED = '#ff2d2d'
with open(os.path.join(ROOT, 'assets', 'warning.json')) as _f:
    CUE = json.load(_f)                  # cue_s (first beep), length_s, beeps_s, beep_s, snap_s
CUE_FRAC = CUE['cue_s'] / CUE['length_s']   # where full damage (Railgun 90%, Epoch full charge) sits along the waveform
YELLOW = '#ffe710'
CYAN = '#6fe6ff'


def font(name):
    return base64.b64encode(open(os.path.join(ART, 'fonts', name), 'rb').read()).decode()


def waveform_path(width, height, columns=260):
    with wave.open(os.path.join(ROOT, 'assets', 'warning.wav')) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').reshape(-1, w.getnchannels()).mean(1) / 32768
    edges = np.linspace(0, len(a), columns + 1).astype(int)
    peak = np.array([np.abs(a[edges[i]:edges[i + 1]]).max() for i in range(columns)])
    peak = peak / peak.max()
    xs = np.linspace(0, width, columns)
    mid = height / 2
    top = ' '.join('%.1f,%.1f' % (x, mid - 0.04 * height - p * 0.46 * height) for x, p in zip(xs, peak))
    bottom = ' '.join('%.1f,%.1f' % (x, mid + 0.04 * height + p * 0.46 * height) for x, p in zip(xs[::-1], peak[::-1]))
    return 'M0,%.1f L%s L%s Z' % (mid, top, bottom)


def scope(width, height):
    """The whole warning as a waveform; a charge meter fills up to the cue (first beep, full damage), then the beeps
    follow as red blocks at their real times."""
    mark_x = CUE_FRAC * width
    x_of = lambda s: s / CUE['length_s'] * width
    seg_w = mark_x / 18
    segs = []
    for i in range(18):
        colour = ['#ffe710', '#ffb000', '#ff6a00', '#ff2d2d'][min(3, i * 20 // 18 // 5)]
        segs.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="%s"/>'
                    % (i * seg_w + 3, height * 0.86, seg_w - 6, height * 0.1, colour))
    for b in CUE['beeps_s']:
        segs.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="%s" filter="url(#glow)"/>'
                    % (x_of(b) + 3, height * 0.86, x_of(CUE['beep_s']) - 2, height * 0.1, RED))
    return f'''<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="wg" x1="0" x2="1"><stop offset="0" stop-color="{CYAN}" stop-opacity="0.55"/>
          <stop offset="{CUE_FRAC * 0.75:.3f}" stop-color="{CYAN}"/><stop offset="{CUE_FRAC:.3f}" stop-color="#ffffff"/>
          <stop offset="{CUE_FRAC + 0.04:.3f}" stop-color="{RED}"/><stop offset="1" stop-color="{RED}"/></linearGradient>
        <filter id="glow" x="-10%" y="-30%" width="120%" height="160%"><feGaussianBlur stdDeviation="{height*0.02:.1f}" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      </defs>
      <line x1="0" x2="{width}" y1="{height*0.38:.1f}" y2="{height*0.38:.1f}" stroke="{CYAN}" stroke-opacity="0.18" stroke-width="2"/>
      <g filter="url(#glow)"><path d="{waveform_path(width, height*0.76)}" fill="url(#wg)"/></g>
      <line x1="{mark_x:.1f}" x2="{mark_x:.1f}" y1="0" y2="{height:.1f}" stroke="{YELLOW}" stroke-width="{max(3,width/260):.1f}" stroke-dasharray="{height*0.04:.1f} {height*0.025:.1f}"/>
      {''.join(segs)}
    </svg>'''


def page(width, height, layout):
    css_fonts = f'''
      @font-face {{ font-family: Anton; src: url(data:font/woff2;base64,{font('anton-latin-400-normal.woff2')}); }}
      @font-face {{ font-family: Barlow; font-weight: 500; src: url(data:font/woff2;base64,{font('barlow-condensed-latin-500-normal.woff2')}); }}
      @font-face {{ font-family: Barlow; font-weight: 600; src: url(data:font/woff2;base64,{font('barlow-condensed-latin-600-normal.woff2')}); }}
      @font-face {{ font-family: Barlow; font-weight: 700; src: url(data:font/woff2;base64,{font('barlow-condensed-latin-700-normal.woff2')}); }}'''
    u = width / 1000
    L = layout
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>{css_fonts}
      html,body {{ margin:0; width:{width}px; height:{height}px; overflow:hidden; background:#08090b; }}
      .bg {{ position:absolute; inset:0;
        background: radial-gradient(ellipse at {L['glow']}, rgba(80,200,255,0.20), rgba(0,0,0,0) 55%),
                    repeating-linear-gradient(0deg, rgba(255,255,255,0.025) 0 1px, transparent 1px {int(28*u)}px),
                    repeating-linear-gradient(90deg, rgba(255,255,255,0.025) 0 1px, transparent 1px {int(28*u)}px); }}
      .stripe {{ position:absolute; {L['stripe']}; background: repeating-linear-gradient(-45deg, {YELLOW} 0 {int(18*u)}px, #111 {int(18*u)}px {int(36*u)}px); }}
      .scope {{ position:absolute; {L['scope']}; }}
      .badge {{ position:absolute; {L['badge']}; background:{YELLOW}; color:#0e0e10; font:{L['badge_size']}px Anton; padding:0 {int(L['badge_size']*0.28)}px; line-height:1.25; }}
      .tag {{ position:absolute; {L['tag']}; text-align:right; font-family:Barlow; font-weight:700; letter-spacing:0.04em; line-height:1.05; }}
      .tag .a {{ color:#fff; font-size:{L['tag_size']}px; font-weight:600; }}
      .tag .b {{ color:{YELLOW}; font-size:{L['tag_size']*1.2:.0f}px; }}
      .title {{ position:absolute; {L['title']}; font-family:Anton; line-height:0.95; text-shadow:0 {int(4*u)}px {int(18*u)}px rgba(0,0,0,0.8); }}
      .title .a {{ color:#fff; font-size:{L['t1']}px; letter-spacing:0.02em; }}
      .title .b {{ color:{YELLOW}; font-size:{L['t2']}px; letter-spacing:0.01em; }}
      .foot {{ position:absolute; {L['foot']}; color:#d8d8d8; font-family:Barlow; font-weight:500; font-size:{L['foot_size']}px; letter-spacing:0.06em; }}
      .mark {{ position:absolute; {L['mark']}; color:{YELLOW}; font-family:Barlow; font-weight:700; font-size:{L['mark_size']}px; letter-spacing:0.05em; }}
    </style></head><body><div class="bg"></div><div class="stripe"></div>
      <div class="scope">{scope(*L['scope_px'])}</div>
      <div class="mark">FULL DAMAGE</div>
      <div class="badge">{BADGE}</div>
      <div class="tag"><div class="a">KNOW EXACTLY</div><div class="b">WHEN TO FIRE</div></div>
      <div class="title"><div class="a">CHARGE</div><div class="b">WARNING &amp; AUTO UNSAFE</div></div>
      <div class="foot">RS-422 RAILGUN &nbsp;&bull;&nbsp; PLAS-45 EPOCH &nbsp;&bull;&nbsp; BEEPS AT FULL DAMAGE &nbsp;&bull;&nbsp; RAILGUN STARTS IN UNSAFE</div>
    </body></html>'''


def px(v): return '%dpx' % v


LAYOUTS = {
    'thumbnail_1254.png': (1254, 1254, dict(
        glow='55% 42%', stripe='left:0; right:0; bottom:0; height:22px',
        scope='left:70px; top:300px', scope_px=(1114, 470), mark='left:%s; top:250px' % px(70 + CUE_FRAC * 1114 + 16), mark_size=40,
        badge='left:70px; top:70px', badge_size=92, tag='right:70px; top:74px', tag_size=46,
        title='left:66px; top:830px', t1=150, t2=118, foot='left:72px; bottom:62px', foot_size=29)),
    'header_1300x372.png': (1300, 372, dict(
        glow='75% 50%', stripe='left:0; right:0; bottom:0; height:10px',
        scope='left:640px; top:70px', scope_px=(610, 250), mark='left:%s; top:40px' % px(640 + CUE_FRAC * 610 + 10), mark_size=26,
        badge='left:40px; top:34px', badge_size=40, tag='right:1000px; top:1000px', tag_size=1,
        title='left:38px; top:100px', t1=96, t2=56, foot='left:42px; bottom:30px', foot_size=21)),
    'gallery_1920x1080.png': (1920, 1080, dict(
        glow='66% 40%', stripe='left:0; right:0; bottom:0; height:18px',
        scope='left:760px; top:230px', scope_px=(1090, 440), mark='left:%s; top:186px' % px(760 + CUE_FRAC * 1090 + 16), mark_size=40,
        badge='left:64px; top:60px', badge_size=92, tag='right:70px; top:64px', tag_size=46,
        title='left:60px; top:640px', t1=150, t2=112, foot='left:66px; bottom:52px', foot_size=34)),
    'GitHub-Social-1280x640.png': (1280, 640, dict(
        glow='68% 38%', stripe='left:0; right:0; bottom:0; height:12px',
        scope='left:560px; top:150px', scope_px=(680, 240), mark='left:%s; top:116px' % px(560 + CUE_FRAC * 680 + 12), mark_size=26,
        badge='left:40px; top:40px', badge_size=60, tag='right:40px; top:40px', tag_size=30,
        title='left:38px; top:378px', t1=104, t2=76, foot='left:42px; bottom:40px', foot_size=24)),
}

def option_icons():
    """Arsenal option icons (256x256): blurred crop of the art, yellow frame, a yellow speaker with 1-4 sound waves."""
    from PIL import ImageDraw, ImageFilter
    os.makedirs(os.path.join(ART, 'options'), exist_ok=True)
    src = Image.open(os.path.join(ART, 'thumbnail_1254.png')).convert('RGB')
    back = src.crop((140, 300, 1140, 800)).resize((1024, 1024)).filter(ImageFilter.GaussianBlur(28))
    back = Image.blend(back, Image.new('RGB', back.size, (8, 9, 11)), 0.62)
    Y = (255, 231, 16)
    for name, waves in (('volume', 3), ('vol_1', 1), ('vol_2', 2), ('vol_3', 3), ('vol_4', 4)):
        im = back.copy()
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 1023, 1023], outline=Y, width=56)
        cx, cy = 300, 512
        d.polygon([(cx - 150, cy - 90), (cx - 60, cy - 90), (cx + 70, cy - 210), (cx + 70, cy + 210), (cx - 60, cy + 90),
                   (cx - 150, cy + 90)], fill=Y)
        for i in range(waves):
            r = 140 + 80 * i
            d.arc([cx + 60 - r, cy - r, cx + 60 + r, cy + r], -48, 48, fill=Y, width=54)
        im.resize((256, 256), Image.LANCZOS).save(os.path.join(ART, 'options', name + '.png'))
    # Auto unsafe mode: an open padlock (safety off) in yellow with a red shackle gap
    im = back.copy()
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1023, 1023], outline=Y, width=56)
    d.rounded_rectangle([262, 470, 762, 830], radius=60, fill=Y)                       # lock body
    d.arc([322, 170, 622, 530], 180, 360, fill=Y, width=70)                             # shackle, swung open to the left
    d.line([(357, 345), (357, 470)], fill=Y, width=70)
    d.line([(587, 345), (587, 400)], fill=(255, 45, 45), width=70)                      # the open side, in red
    d.ellipse([472, 590, 552, 670], fill=(14, 14, 16)); d.rectangle([497, 640, 527, 740], fill=(14, 14, 16))   # keyhole
    im.resize((256, 256), Image.LANCZOS).save(os.path.join(ART, 'options', 'unsafe.png'))
    weapon_icons(back)


def _waves(d, cx, cy, n=2, colour=(255, 45, 45)):
    for i in range(n):
        r = 90 + 70 * i
        d.arc([cx - r, cy - r, cx + r, cy + r], -50, 50, fill=colour, width=44)


def weapon_icons(back):
    """One icon per weapon option: the weapon's charge drawn simply, with red warning waves on the right.
    Railgun: two long rails with a charged bolt between them. Epoch: a plasma orb held by charging coils."""
    from PIL import ImageDraw, ImageFilter
    Y, C, W = (255, 231, 16), (111, 230, 255), (235, 250, 255)
    def framed(draw_fn, glow_fn):
        glow = Image.new('RGB', (1024, 1024), (0, 0, 0))
        glow_fn(ImageDraw.Draw(glow))
        glow = glow.filter(ImageFilter.GaussianBlur(26))
        im = Image.fromarray(np.clip(np.asarray(back, dtype=np.int16) + np.asarray(glow, dtype=np.int16), 0, 255).astype('uint8'))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 1023, 1023], outline=Y, width=56)
        draw_fn(d)
        return im
    # Railgun: rails from the left, bolt between them, waves at the muzzle
    def rail(d):
        d.rectangle([110, 340, 690, 440], fill=Y); d.rectangle([110, 584, 690, 684], fill=Y)
        d.rectangle([110, 440, 190, 584], fill=Y)                                   # breech block
        d.rectangle([200, 486, 680, 538], fill=W)                                   # the charged bolt
        _waves(d, 720, 512)
    def rail_glow(d):
        d.rectangle([190, 450, 700, 574], fill=C)
    framed(rail, rail_glow).resize((256, 256), Image.LANCZOS).save(os.path.join(ART, 'options', 'railgun.png'))
    # Epoch: orb with three coil rings around it, waves on the right
    def epoch(d):
        cx, cy = 400, 512
        d.ellipse([cx - 150, cy - 150, cx + 150, cy + 150], fill=W)
        for dx in (-200, 0, 200):
            d.arc([cx + dx - 60, cy - 230, cx + dx + 60, cy + 230], 0, 360, fill=Y, width=46)
        _waves(d, 640, 512)
    def epoch_glow(d):
        d.ellipse([400 - 230, 512 - 230, 400 + 230, 512 + 230], fill=C)
    framed(epoch, epoch_glow).resize((256, 256), Image.LANCZOS).save(os.path.join(ART, 'options', 'epoch.png'))


if __name__ == '__main__':
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, (w, h, layout) in LAYOUTS.items():
            pg = browser.new_page(viewport={'width': w, 'height': h})
            pg.set_content(page(w, h, layout))
            pg.wait_for_timeout(300)
            pg.screenshot(path=os.path.join(ART, name))
            pg.close()
        browser.close()
    Image.open(os.path.join(ART, 'thumbnail_1254.png')).resize((512, 512), Image.LANCZOS).save(os.path.join(ART, 'thumbnail_512.png'))
    option_icons()
    print('art done')
