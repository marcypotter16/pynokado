#version 330

// Additive hover-glow pass. Runs after the main game texture is on screen.
// Draws a soft, pulsing glow in a band *around* the hovered card's rectangle,
// so it reads as light bleeding out from under/behind a lifted card.

uniform sampler2D tex;      // the already-rendered game texture (for readback)
uniform vec2  u_res;        // game resolution in pixels (1920x1080)
uniform vec4  u_rect;       // hovered card rect in pixels: x, y, w, h (top-left origin)
uniform vec3  u_color;      // glow colour (0..1)
uniform float u_time;       // seconds, for the pulse
uniform float u_intensity;  // 0..1 master strength (fades in/out with the lift)
uniform float u_radius;     // glow falloff distance in pixels

in vec2 v_uv;
out vec4 fragColor;

void main() {
    // v_uv has flipped Y (see quad + tobytes flip). Work in pixel space with a
    // top-left origin to match the card rect we get from Python.
    vec2 px = vec2(v_uv.x, 1.0 - v_uv.y) * u_res;

    // Signed distance to the card rectangle (0 inside, grows outside).
    vec2 c = u_rect.xy + u_rect.zw * 0.5;      // rect centre
    vec2 half_size = u_rect.zw * 0.5;
    vec2 d = abs(px - c) - half_size;
    float dist = length(max(d, 0.0));          // distance outside the rect

    // Glow lives in a band just outside the border; 1 at the edge -> 0 at u_radius.
    float glow = 1.0 - smoothstep(0.0, u_radius, dist);
    glow = pow(glow, 1.6);                      // tighten toward the edge

    // Gentle pulse.
    float pulse = 0.75 + 0.25 * sin(u_time * 3.0);

    // Only outside the card (don't wash out the art itself).
    float outside = step(0.001, dist);

    float a = glow * pulse * u_intensity * outside;

    // Premultiplied additive-ish colour; blended with SRC_ALPHA/ONE_MINUS_SRC_ALPHA.
    fragColor = vec4(u_color * a, a);
}
