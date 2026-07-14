#version 330

// Additive hover-glow pass. Runs once, after the main game texture is on
// screen, and draws a soft pulsing glow in a band *around* each lifted card.
// All lifted cards are fed in as arrays and accumulated in a single draw, so
// moving between cards cross-fades continuously (no per-card draw calls, no
// glow "teleport").

const int MAX_CARDS = 12;

uniform vec2  u_res;                     // game resolution in pixels
uniform int   u_count;                   // number of active glows
uniform vec4  u_rects[MAX_CARDS];        // card rects: x, y, w, h (top-left origin)
uniform vec3  u_colors[MAX_CARDS];       // per-card glow colour (0..1)
uniform float u_intensities[MAX_CARDS];  // per-card strength (lift, 0..1)
uniform float u_time;                    // seconds, for the pulse
uniform float u_radius;                  // glow falloff distance in pixels

in vec2 v_uv;
out vec4 fragColor;

// Glow contribution of one card rect at pixel `px`, as premultiplied RGBA.
vec4 card_glow(vec2 px, vec4 rect, vec3 color, float intensity) {
    vec2 c = rect.xy + rect.zw * 0.5;
    vec2 half_size = rect.zw * 0.5;
    vec2 d = abs(px - c) - half_size;
    float dist = length(max(d, 0.0));          // distance outside the rect

    float glow = 1.0 - smoothstep(0.0, u_radius, dist);
    glow = pow(glow, 1.6);                       // tighten toward the edge
    float outside = step(0.001, dist);           // don't wash out the card face

    float a = glow * intensity * outside;
    return vec4(color * a, a);
}

void main() {
    // Buffer is uploaded top-row-first; flip V to get top-left pixel origin.
    vec2 px = vec2(v_uv.x, 1.0 - v_uv.y) * u_res;

    // Single gentle pulse shared by all cards.
    float pulse = 0.75 + 0.25 * sin(u_time * 3.0);

    // Accumulate every active card's glow.
    vec4 acc = vec4(0.0);
    for (int i = 0; i < MAX_CARDS; i++) {
        if (i >= u_count) break;
        acc += card_glow(px, u_rects[i], u_colors[i], u_intensities[i]);
    }
    acc *= pulse;

    fragColor = vec4(acc.rgb, min(acc.a, 1.0));
}
