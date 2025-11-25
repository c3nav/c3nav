// Worker for 39C3 animation canvas
let canvas, ctx, frame;

// Listen for the canvas from c3nav main thread
self.onmessage = (e) => {
    if (e.data.canvas !== undefined) {
      canvas = e.data.canvas;
      ctx = canvas.getContext("2d");
      setup();
    }

    if (e.data.pause)
      cancelAnimationFrame(frame);
    else
      frame = requestAnimationFrame(draw);
};

// The text and x y coords within canvas
const text = "C3NAV";
const baseX = 0;
const baseY = 49;

// min max weight and how many steps/how smooth
const minWeight = 100;
const maxWeight = 900;
const weightStep = 10;

// which font and size
const fontSize = 32;
const fontFamily = "Inter, sans-serif";

// time between frames
const speed = 0.005;
// time between letters (phase)
const phaseDist = 0.7;

const charWidths = {};
const charCache = {};

// pre render every char and measure it's weight
function setup() {
    for (let weight = minWeight; weight <= maxWeight; weight += weightStep) {
        charCache[weight] = {};
        charWidths[weight] = {};
        [...text].forEach(ch => {
            const tmpCanvas = new OffscreenCanvas(100, 120);
            const tmpCtx = tmpCanvas.getContext("2d");
            tmpCtx.font = `${weight} ${fontSize}px ${fontFamily}`;
            tmpCtx.fillStyle = "white";
            tmpCtx.textBaseline = "top";
            tmpCtx.fillText(ch, 0, 0);
            charCache[weight][ch] = tmpCanvas;
            charWidths[weight][ch] = tmpCtx.measureText(ch).width;
        });
    }
}

function draw(t) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    let x = baseX;
    for (let i = 0; i < text.length; i++) {
        const phase = t * speed + i * phaseDist;
        // smooth out the phase by approximating it to a sine wave
        const sine = (Math.sin(phase) + 1) / 2;

        // get prerendered canvas and width
        let weight = minWeight + sine * (maxWeight - minWeight);
        weight = Math.round(weight / weightStep) * weightStep;
        weight = Math.min(Math.max(weight, minWeight), maxWeight);

        const charCanvas = charCache[weight][text[i]];
        ctx.drawImage(charCanvas, x, baseY - fontSize);

        x += charWidths[weight][text[i]] + 5;
    }

    frame = requestAnimationFrame(draw);
}