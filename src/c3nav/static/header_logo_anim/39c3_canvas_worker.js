// Worker for 39C3 animation canvas
let canvas, ctx, frame;
let dpr = 1.0;

// The text and x y coords within canvas
let text = "C3NAV";

// min max weight and how many steps/how smooth
const minWeight = 10;
const maxWeight = 100;
const weightStep = 5;

// which font and size
const fontSize = 30;
const fontFamily = 'KarioDuplexVar';
const fontFallback = 'sans-serif';
const fontURL = "url('/static/39c3/fonts/Kario39C3VarWEB-Roman.woff2')";
const fontStyle = {
    style: "normal",
    weight: "10 100"
};
const letterSpacing = 0;

// time between frames
const speed = 0.004;
// time between letters (phase)
const phaseDist = 0.7;

const font = new FontFace(fontFamily, fontURL, fontStyle);

let startTime = null;

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
            setup();
        }, (err) => {
            // Setup anyway, it will fallback unless font is installed on system
            setup();
        });
    }

    if (e.data.pause)
        cancelAnimationFrame(frame);
    else
        frame = requestAnimationFrame(draw);
};

const charWidths = {};
const charCache = {};

// pre render every char and measure it's weight
function setup() {
    for (let weight = minWeight; weight <= maxWeight; weight += weightStep) {
        charCache[weight] = {};
        charWidths[weight] = {};
        [...text].forEach(ch => {
            const tmpCanvas = new OffscreenCanvas(fontSize*dpr, fontSize*dpr);
            const tmpCtx = tmpCanvas.getContext("2d");
            tmpCtx.fontKerning = "none";
            tmpCtx.font = `${weight} ${fontSize*dpr}px ${fontFamily}, ${fontFallback}`;
            tmpCtx.fillStyle = "white";
            tmpCtx.textBaseline = "top";
            tmpCtx.fillText(ch, 0, 0);
            charCache[weight][ch] = tmpCanvas;
            charWidths[weight][ch] = tmpCtx.measureText(ch).width;
        });
    }
}

function draw(t) {
    // Check if glyphs are rendered yet
    if (Object.keys(charCache).length !== 0) {
        // We want t to start at zero so the animation starts always at the same point, so we store the first start time and do t - startTime
        if (startTime === null)
            startTime = t;
        
        ctx.clearRect(0, 0, canvas.width, canvas.height);

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
        }
    }
    frame = requestAnimationFrame(draw);
}