// Demo worker for animation canvas
let canvas, ctx, frame;

// Listen for the canvas from c3nav main thread
self.onmessage = (e) => {
    // Set it all up
    if (e.data.canvas !== undefined) {
      canvas = e.data.canvas;
      ctx = canvas.getContext("2d");
      setup();
    }

    // Pause logic, frame keeps reference
    if (e.data.pause)
      cancelAnimationFrame(frame);
    else
      frame = requestAnimationFrame(draw);
};

// Text, Coords and Initial Direction (0 or 1)
var text = "C3NAV";
var x = 0;
var y = 43;
var dir = 1;

var grad;
var width;

function setup() {
    // Which font to use
    ctx.font = "32px Inter, sans-serif";
    // Define a gradient across the width of the canvas so anything that is drawn onto it is colorful :3
    grad = ctx.createLinearGradient(0, 0, canvas.width, 0);
    grad.addColorStop(0, "blue");
    grad.addColorStop(0.5, "red");
    grad.addColorStop(1, "blue");
    ctx.fillStyle = grad;
    //ctx.fillStyle = "white";
    width = ctx.measureText(text).width;
}

function draw(t) {
    // Yeet everyting
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    x += dir;

    // Reverse direction when end reached
    if (x > canvas.width - width || x < 0) {
      dir *= -1;
    }

    // Render text at pos
    ctx.fillText(text, x, y);

    // Do it again
    frame = requestAnimationFrame(draw);
}
