// Worker for 39C3 animation canvas
let canvas, ctx, frame;
let dpr = 1.0;

// The text and x y coords within canvas
let text = "C3NAV⏼";

// min max weight for fallback and how many steps/how smooth
var minWeight = 100;
var maxWeight = 900;
var weightStep = 10;

// which font and size
const fontSize = 30;
const fontFamily = 'KarioDuplexVar';
const fontFallback = 'monospace';
const fontURL = "url('/static/39c3/fonts/Kario39C3VarWEB-Roman.woff2')";
// min max weight for font and how many steps/how smooth
const fontMinWeight = 10;
const fontMaxWeight = 100;
const fontWeightStep = 5;
const fontStyle = {
    style: "normal",
    weight: "10 100"
};
const letterSpacing = 0;

// time between frames
const speed = 0.0035;
// time between letters (phase) the number of the beast = 120deg = grid phase difference = power cycles
const phaseDist = 0.666;

const font = new FontFace(fontFamily, fontURL, fontStyle);

let startTime = null;
let requestPause = false;

// Listen for the canvas from c3nav main thread
self.onmessage = (e) => {
    if (e.data.canvas !== undefined) {
        canvas = e.data.canvas;
        dpr = e.data.dpr;
        ctx = canvas.getContext("2d");

        if (e.data.text && e.data.text.toUpperCase() !== text.toUpperCase())
            text = e.data.text.toUpperCase();
        
        font.load().then(() => {
            // Setup with loaded font
            self.fonts.add(font);
            minWeight = fontMinWeight;
            maxWeight = fontMaxWeight;
            weightStep = fontWeightStep;
            setup();
        }, (err) => {
            console.error(err);
        });

        // Setup anyway, it will fallback unless font is installed on system
        setup();
    }

    if (e.data.pause) {
        requestPause = true;
    } else {
        if (!requestPause)
            startTime = null;

        requestPause = false;
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(draw);
    }
};

const charWidths = {};
const charCache = {};

// pre render every char and measure it's weight
function setup() {
    for (let weight = minWeight; weight <= maxWeight; weight += weightStep) {
        charCache[weight] = {};
        charWidths[weight] = {};
        [...text].forEach(ch => {
            var str = ch;
            var wModifier = 1;
            if (ch == "⏼") {
                str = " <<toggle";
                wModifier = 2;
            }
            const tmpCanvas = new OffscreenCanvas((fontSize*wModifier)*dpr, fontSize*dpr);
            const tmpCtx = tmpCanvas.getContext("2d");
            tmpCtx.fontKerning = "none";
            tmpCtx.font = `${weight} ${fontSize*dpr}px ${fontFamily}, ${fontFallback}`;
            tmpCtx.fillStyle = "white";
            tmpCtx.textBaseline = "top";
            tmpCtx.fillText(str, 0, 0);
            charCache[weight][ch] = tmpCanvas;
            charWidths[weight][ch] = tmpCtx.measureText(str).width;
        });
    }
}

// something something power cycles... grid overlad simulation meow
function gridFluctuations () {
    // current time in seconds
    let t = performance.now() / 1000

    // emulate sag (0.5 Hz) + faster wobble (3 Hz) from stuff like motors, compressors, fairydust taking off or whatever
    // real flicker creatures notice is usually 1-8 Hz, so these are in that area (IEC 61000:4:15)
    let wobble = Math.sin(t * 3) + Math.sin(t * 0.5) * 0.6;

    // incandescent bulbs respond to RMS voltage
    // squaring a 50 Hz sine results in 100 Hz flicker, barely visible
    let ripple = Math.sin(2 * Math.PI * 50 * t);
    // If you multiply it with itself it will be a positive number...
    ripple = ripple * ripple;

    // lets assume baseline voltage is at 92% of usual because there is a bunch of load
    // wobble range 5%, this might be noticeable
    // ripple 1%, at this point you mostly just feeling rather than seeing it, but maybe with two cee bee or other fairydusts you notice....
    let v = 0.92 + (wobble * 0.05) + (ripple * 0.01);

    // clamp so it never gets totally dark
    // don't let it fall below ~84% of nominal, otherwise it looks like blackout
    if (v < 0.84)
        v = 0.84;

    // cap voltage at 100%
    if (v > 1)
        v = 1;

    // incandescent bulbs are disproportionatly sensitive to voltage, flux or something, i dunno i only understood half of it
    // flux to the power of 2.4 (instead of ~V^3) is a compromise adjusted to screen gamma, GE has some technical docs on their incandescent lights
    // 0.25 brightness offset and clamping the minimum at 0.85 keeps min alpha from being too low to be visible/greyish
    var alpha = 0.25 + Math.pow(v, 2.4) * 0.85

    // At this point at least make the text 100% brightness sometimes and ignore 99-100% range
    if (alpha >= 0.99)
        alpha = 1.0;
    
    return alpha;

}

function draw(t) {
    // Check if glyphs are rendered yet
    if (Object.keys(charCache).length !== 0) {
        // We want t to start at zero so the animation starts always at the same point, so we store the first start time and do t - startTime
        if (startTime === null)
            startTime = t;
        
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        ctx.globalAlpha = gridFluctuations();
        //console.log(ctx.globalAlpha);
        
        let x = 0;
        for (let i = 0; i < text.length; i++) {
            const phase = (t - startTime) * speed + i * phaseDist;
            // smooth out the phase by approximating it to a cosine wave
            const cosine = (1 - Math.cos(phase)) / 2;

            // get prerendered canvas and width
            let weight = minWeight + cosine * (maxWeight - minWeight);
            weight = Math.round(weight / weightStep) * weightStep;
            weight = Math.min(Math.max(weight, minWeight), maxWeight);

            const charCanvas = charCache[weight][text[i]];
            // Position rendered char at width offset and centered height
            ctx.drawImage(charCanvas, x, (canvas.height - (fontSize * dpr / 2)) - fontSize * dpr);

            x += charWidths[weight][text[i]] + letterSpacing;

            if (requestPause && weight == maxWeight && i == (text.length - 1)) {
                self.postMessage({ animCompleted: true });
                cancelAnimationFrame(frame);
                requestPause = false;
                return;
            }
        }
    }
    frame = requestAnimationFrame(draw);
}