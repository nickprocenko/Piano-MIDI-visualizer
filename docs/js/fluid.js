/*
MIT License
Copyright (c) 2017 Pavel Dobryakov
Adapted as ES module class for Piano MIDI Visualizer.
*/

export class FluidSimulation {
  constructor (canvas, options = {}) {
    this.canvas = canvas;
    this.config = {
      SIM_RESOLUTION: options.SIM_RESOLUTION ?? 128,
      DYE_RESOLUTION: options.DYE_RESOLUTION ?? 512,
      DENSITY_DISSIPATION: options.DENSITY_DISSIPATION ?? 1.0,
      VELOCITY_DISSIPATION: options.VELOCITY_DISSIPATION ?? 0.2,
      PRESSURE: options.PRESSURE ?? 0.8,
      PRESSURE_ITERATIONS: options.PRESSURE_ITERATIONS ?? 20,
      CURL: options.CURL ?? 30,
      SPLAT_RADIUS: options.SPLAT_RADIUS ?? 0.25,
      SPLAT_FORCE: options.SPLAT_FORCE ?? 6000,
      SHADING: false,
      BLOOM: options.BLOOM ?? true,
      BLOOM_ITERATIONS: options.BLOOM_ITERATIONS ?? 8,
      BLOOM_RESOLUTION: options.BLOOM_RESOLUTION ?? 256,
      BLOOM_INTENSITY: options.BLOOM_INTENSITY ?? 0.8,
      BLOOM_THRESHOLD: options.BLOOM_THRESHOLD ?? 0.6,
      BLOOM_SOFT_KNEE: options.BLOOM_SOFT_KNEE ?? 0.7,
      SUNRAYS: options.SUNRAYS ?? true,
      SUNRAYS_RESOLUTION: options.SUNRAYS_RESOLUTION ?? 196,
      SUNRAYS_WEIGHT: options.SUNRAYS_WEIGHT ?? 1.0,
      TRANSPARENT: true,
    };

    const { gl, ext } = this._getWebGLContext(canvas);
    this.gl = gl;
    this.ext = ext;

    if (!ext.supportLinearFiltering) {
      this.config.DYE_RESOLUTION = 256;
      this.config.BLOOM = false;
      this.config.SUNRAYS = false;
    }

    this._initShaders(options);
    this._initFramebuffers();
    this._updateKeywords();
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  step (dt) {
    const { gl, config } = this;
    gl.disable(gl.BLEND);

    this.curlProgram.bind();
    gl.uniform2f(this.curlProgram.uniforms.texelSize, this.velocity.texelSizeX, this.velocity.texelSizeY);
    gl.uniform1i(this.curlProgram.uniforms.uVelocity, this.velocity.read.attach(0));
    this._blit(this.curl);

    this.vorticityProgram.bind();
    gl.uniform2f(this.vorticityProgram.uniforms.texelSize, this.velocity.texelSizeX, this.velocity.texelSizeY);
    gl.uniform1i(this.vorticityProgram.uniforms.uVelocity, this.velocity.read.attach(0));
    gl.uniform1i(this.vorticityProgram.uniforms.uCurl, this.curl.attach(1));
    gl.uniform1f(this.vorticityProgram.uniforms.curl, config.CURL);
    gl.uniform1f(this.vorticityProgram.uniforms.dt, dt);
    this._blit(this.velocity.write);
    this.velocity.swap();

    this.divergenceProgram.bind();
    gl.uniform2f(this.divergenceProgram.uniforms.texelSize, this.velocity.texelSizeX, this.velocity.texelSizeY);
    gl.uniform1i(this.divergenceProgram.uniforms.uVelocity, this.velocity.read.attach(0));
    this._blit(this.divergence);

    this.clearProgram.bind();
    gl.uniform1i(this.clearProgram.uniforms.uTexture, this.pressure.read.attach(0));
    gl.uniform1f(this.clearProgram.uniforms.value, config.PRESSURE);
    this._blit(this.pressure.write);
    this.pressure.swap();

    this.pressureProgram.bind();
    gl.uniform2f(this.pressureProgram.uniforms.texelSize, this.velocity.texelSizeX, this.velocity.texelSizeY);
    gl.uniform1i(this.pressureProgram.uniforms.uDivergence, this.divergence.attach(0));
    for (let i = 0; i < config.PRESSURE_ITERATIONS; i++) {
      gl.uniform1i(this.pressureProgram.uniforms.uPressure, this.pressure.read.attach(1));
      this._blit(this.pressure.write);
      this.pressure.swap();
    }

    this.gradientSubtractProgram.bind();
    gl.uniform2f(this.gradientSubtractProgram.uniforms.texelSize, this.velocity.texelSizeX, this.velocity.texelSizeY);
    gl.uniform1i(this.gradientSubtractProgram.uniforms.uPressure, this.pressure.read.attach(0));
    gl.uniform1i(this.gradientSubtractProgram.uniforms.uVelocity, this.velocity.read.attach(1));
    this._blit(this.velocity.write);
    this.velocity.swap();

    this.advectionProgram.bind();
    gl.uniform2f(this.advectionProgram.uniforms.texelSize, this.velocity.texelSizeX, this.velocity.texelSizeY);
    if (!this.ext.supportLinearFiltering)
      gl.uniform2f(this.advectionProgram.uniforms.dyeTexelSize, this.velocity.texelSizeX, this.velocity.texelSizeY);
    const velocityId = this.velocity.read.attach(0);
    gl.uniform1i(this.advectionProgram.uniforms.uVelocity, velocityId);
    gl.uniform1i(this.advectionProgram.uniforms.uSource, velocityId);
    gl.uniform1f(this.advectionProgram.uniforms.dt, dt);
    gl.uniform1f(this.advectionProgram.uniforms.dissipation, config.VELOCITY_DISSIPATION);
    this._blit(this.velocity.write);
    this.velocity.swap();

    if (!this.ext.supportLinearFiltering)
      gl.uniform2f(this.advectionProgram.uniforms.dyeTexelSize, this.dye.texelSizeX, this.dye.texelSizeY);
    gl.uniform1i(this.advectionProgram.uniforms.uVelocity, this.velocity.read.attach(0));
    gl.uniform1i(this.advectionProgram.uniforms.uSource, this.dye.read.attach(1));
    gl.uniform1f(this.advectionProgram.uniforms.dissipation, config.DENSITY_DISSIPATION);
    this._blit(this.dye.write);
    this.dye.swap();
  }

  render () {
    const { gl, config } = this;
    if (config.BLOOM) this._applyBloom(this.dye.read, this.bloom);
    if (config.SUNRAYS) {
      this._applySunrays(this.dye.read, this.dye.write, this.sunrays);
      this._blur(this.sunrays, this.sunraysTemp, 1);
    }
    gl.disable(gl.BLEND);
    this._drawDisplay(null);
  }

  // normX, normY in [0,1] (Y=0 top), velX/velY in normalised sim units
  addSplat (normX, normY, velX, velY, r, g, b, radiusOverride, dyeRadiusOverride) {
    const { gl, config, canvas } = this;
    const velocityRadius = radiusOverride != null
      ? this._correctRadius(radiusOverride)
      : this._correctRadius(config.SPLAT_RADIUS / 100.0);
    const dyeRadius = dyeRadiusOverride != null
      ? this._correctRadius(dyeRadiusOverride)
      : velocityRadius;

    const texY = 1.0 - normY;

    this.splatProgram.bind();
    gl.uniform1i(this.splatProgram.uniforms.uTarget, this.velocity.read.attach(0));
    gl.uniform1f(this.splatProgram.uniforms.aspectRatio, canvas.width / canvas.height);
    gl.uniform2f(this.splatProgram.uniforms.point, normX, texY);
    gl.uniform3f(this.splatProgram.uniforms.color, velX * config.SPLAT_FORCE, -velY * config.SPLAT_FORCE, 0.0);
    gl.uniform1f(this.splatProgram.uniforms.radius, velocityRadius);
    this._blit(this.velocity.write);
    this.velocity.swap();

    gl.uniform1i(this.splatProgram.uniforms.uTarget, this.dye.read.attach(0));
    gl.uniform3f(this.splatProgram.uniforms.color, r, g, b);
    gl.uniform1f(this.splatProgram.uniforms.radius, dyeRadius);
    this._blit(this.dye.write);
    this.dye.swap();
  }

  resize () { this._initFramebuffers(); }

  updateConfig (patch) {
    Object.assign(this.config, patch);
    this._updateKeywords();
  }

  // ── Private: WebGL setup ──────────────────────────────────────────────────

  _getWebGLContext (canvas) {
    const params = { alpha: true, depth: false, stencil: false, antialias: false, preserveDrawingBuffer: false };
    let gl = canvas.getContext('webgl2', params);
    const isWebGL2 = !!gl;
    if (!isWebGL2)
      gl = canvas.getContext('webgl', params) || canvas.getContext('experimental-webgl', params);

    let halfFloat, supportLinearFiltering;
    if (isWebGL2) {
      gl.getExtension('EXT_color_buffer_float');
      supportLinearFiltering = gl.getExtension('OES_texture_float_linear');
    } else {
      halfFloat = gl.getExtension('OES_texture_half_float');
      supportLinearFiltering = gl.getExtension('OES_texture_half_float_linear');
    }

    gl.clearColor(0.0, 0.0, 0.0, 0.0);

    const halfFloatTexType = isWebGL2 ? gl.HALF_FLOAT : halfFloat.HALF_FLOAT_OES;
    let formatRGBA, formatRG, formatR;
    if (isWebGL2) {
      formatRGBA = this._getSupportedFormat(gl, gl.RGBA16F, gl.RGBA, halfFloatTexType);
      formatRG   = this._getSupportedFormat(gl, gl.RG16F,   gl.RG,   halfFloatTexType);
      formatR    = this._getSupportedFormat(gl, gl.R16F,    gl.RED,  halfFloatTexType);
    } else {
      formatRGBA = this._getSupportedFormat(gl, gl.RGBA, gl.RGBA, halfFloatTexType);
      formatRG   = this._getSupportedFormat(gl, gl.RGBA, gl.RGBA, halfFloatTexType);
      formatR    = this._getSupportedFormat(gl, gl.RGBA, gl.RGBA, halfFloatTexType);
    }
    return { gl, ext: { formatRGBA, formatRG, formatR, halfFloatTexType, supportLinearFiltering, isWebGL2 } };
  }

  _getSupportedFormat (gl, internalFormat, format, type) {
    if (!this._supportRenderTextureFormat(gl, internalFormat, format, type)) {
      if (internalFormat === gl.R16F)  return this._getSupportedFormat(gl, gl.RG16F,   gl.RG,   type);
      if (internalFormat === gl.RG16F) return this._getSupportedFormat(gl, gl.RGBA16F, gl.RGBA, type);
      return null;
    }
    return { internalFormat, format };
  }

  _supportRenderTextureFormat (gl, internalFormat, format, type) {
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, internalFormat, 4, 4, 0, format, type, null);
    const fbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    return gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
  }

  // ── Private: Shaders ─────────────────────────────────────────────────────

  _initShaders (options = {}) {
    const gl = this.gl;
    const ext = this.ext;

    this._baseVertexShader = this._compileShader(gl.VERTEX_SHADER, `
      precision highp float;
      attribute vec2 aPosition;
      varying vec2 vUv;
      varying vec2 vL;
      varying vec2 vR;
      varying vec2 vT;
      varying vec2 vB;
      uniform vec2 texelSize;
      void main () {
        vUv = aPosition * 0.5 + 0.5;
        vL = vUv - vec2(texelSize.x, 0.0);
        vR = vUv + vec2(texelSize.x, 0.0);
        vT = vUv + vec2(0.0, texelSize.y);
        vB = vUv - vec2(0.0, texelSize.y);
        gl_Position = vec4(aPosition, 0.0, 1.0);
      }`);

    this._blurVertexShader = this._compileShader(gl.VERTEX_SHADER, `
      precision highp float;
      attribute vec2 aPosition;
      varying vec2 vUv;
      varying vec2 vL;
      varying vec2 vR;
      uniform vec2 texelSize;
      void main () {
        vUv = aPosition * 0.5 + 0.5;
        float offset = 1.33333333;
        vL = vUv - texelSize * offset;
        vR = vUv + texelSize * offset;
        gl_Position = vec4(aPosition, 0.0, 1.0);
      }`);

    const copyShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision mediump float;
      precision mediump sampler2D;
      varying highp vec2 vUv;
      uniform sampler2D uTexture;
      void main () { gl_FragColor = texture2D(uTexture, vUv); }`);

    const clearShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision mediump float;
      precision mediump sampler2D;
      varying highp vec2 vUv;
      uniform sampler2D uTexture;
      uniform float value;
      void main () { gl_FragColor = value * texture2D(uTexture, vUv); }`);

    const displayShaderSource = `
      precision highp float;
      precision highp sampler2D;
      varying vec2 vUv;
      varying vec2 vL;
      varying vec2 vR;
      varying vec2 vT;
      varying vec2 vB;
      uniform sampler2D uTexture;
      uniform sampler2D uBloom;
      uniform sampler2D uSunrays;
      uniform sampler2D uDithering;
      uniform vec2 ditherScale;
      uniform vec2 texelSize;
      vec3 linearToGamma (vec3 color) {
        color = max(color, vec3(0.0));
        return max(1.055 * pow(color, vec3(0.416666667)) - 0.055, vec3(0.0));
      }
      void main () {
        vec3 c = texture2D(uTexture, vUv).rgb;
      #ifdef SHADING
        vec3 lc = texture2D(uTexture, vL).rgb;
        vec3 rc = texture2D(uTexture, vR).rgb;
        vec3 tc = texture2D(uTexture, vT).rgb;
        vec3 bc = texture2D(uTexture, vB).rgb;
        float dx = length(rc) - length(lc);
        float dy = length(tc) - length(bc);
        vec3 n = normalize(vec3(dx, dy, length(texelSize)));
        vec3 l = vec3(0.0, 0.0, 1.0);
        float diffuse = clamp(dot(n, l) + 0.7, 0.7, 1.0);
        c *= diffuse;
      #endif
      #ifdef BLOOM
        vec3 bloom = texture2D(uBloom, vUv).rgb;
      #endif
      #ifdef SUNRAYS
        float sunrays = texture2D(uSunrays, vUv).r;
        c *= sunrays;
      #ifdef BLOOM
        bloom *= sunrays;
      #endif
      #endif
      #ifdef BLOOM
        float noise = texture2D(uDithering, vUv * ditherScale).r;
        noise = noise * 2.0 - 1.0;
        bloom += noise / 255.0;
        bloom = linearToGamma(bloom);
        c += bloom;
      #endif
        float a = max(c.r, max(c.g, c.b));
        gl_FragColor = vec4(c, a);
      }`;

    const blurShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision mediump float;
      precision mediump sampler2D;
      varying vec2 vUv;
      varying vec2 vL;
      varying vec2 vR;
      uniform sampler2D uTexture;
      void main () {
        vec4 sum = texture2D(uTexture, vUv) * 0.29411764;
        sum += texture2D(uTexture, vL) * 0.35294117;
        sum += texture2D(uTexture, vR) * 0.35294117;
        gl_FragColor = sum;
      }`);

    const bloomPrefilterShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision mediump float;
      precision mediump sampler2D;
      varying vec2 vUv;
      uniform sampler2D uTexture;
      uniform vec3 curve;
      uniform float threshold;
      void main () {
        vec3 c = texture2D(uTexture, vUv).rgb;
        float br = max(c.r, max(c.g, c.b));
        float rq = clamp(br - curve.x, 0.0, curve.y);
        rq = curve.z * rq * rq;
        c *= max(rq, br - threshold) / max(br, 0.0001);
        gl_FragColor = vec4(c, 0.0);
      }`);

    const bloomBlurShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision mediump float;
      precision mediump sampler2D;
      varying vec2 vL;
      varying vec2 vR;
      varying vec2 vT;
      varying vec2 vB;
      uniform sampler2D uTexture;
      void main () {
        vec4 sum = vec4(0.0);
        sum += texture2D(uTexture, vL);
        sum += texture2D(uTexture, vR);
        sum += texture2D(uTexture, vT);
        sum += texture2D(uTexture, vB);
        gl_FragColor = sum * 0.25;
      }`);

    const bloomFinalShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision mediump float;
      precision mediump sampler2D;
      varying vec2 vL;
      varying vec2 vR;
      varying vec2 vT;
      varying vec2 vB;
      uniform sampler2D uTexture;
      uniform float intensity;
      void main () {
        vec4 sum = vec4(0.0);
        sum += texture2D(uTexture, vL);
        sum += texture2D(uTexture, vR);
        sum += texture2D(uTexture, vT);
        sum += texture2D(uTexture, vB);
        gl_FragColor = sum * 0.25 * intensity;
      }`);

    const sunraysMaskShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision highp float;
      precision highp sampler2D;
      varying vec2 vUv;
      uniform sampler2D uTexture;
      void main () {
        vec4 c = texture2D(uTexture, vUv);
        float br = max(c.r, max(c.g, c.b));
        c.a = 1.0 - min(max(br * 20.0, 0.0), 0.8);
        gl_FragColor = c;
      }`);

    const sunraysShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision highp float;
      precision highp sampler2D;
      varying vec2 vUv;
      uniform sampler2D uTexture;
      uniform float weight;
      #define ITERATIONS 16
      void main () {
        float Density = 0.3;
        float Decay = 0.95;
        float Exposure = 0.7;
        vec2 coord = vUv;
        vec2 dir = vUv - 0.5;
        dir *= 1.0 / float(ITERATIONS) * Density;
        float illuminationDecay = 1.0;
        float color = texture2D(uTexture, vUv).a;
        for (int i = 0; i < ITERATIONS; i++) {
          coord -= dir;
          float col = texture2D(uTexture, coord).a;
          color += col * illuminationDecay * weight;
          illuminationDecay *= Decay;
        }
        gl_FragColor = vec4(color * Exposure, 0.0, 0.0, 1.0);
      }`);

    const splatShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision highp float;
      precision highp sampler2D;
      varying vec2 vUv;
      uniform sampler2D uTarget;
      uniform float aspectRatio;
      uniform vec3 color;
      uniform vec2 point;
      uniform float radius;
      void main () {
        vec2 p = vUv - point.xy;
        p.x *= aspectRatio;
        vec3 splat = exp(-dot(p, p) / radius) * color;
        vec3 base = texture2D(uTarget, vUv).xyz;
        gl_FragColor = vec4(base + splat, 1.0);
      }`);

    const advectionShader = this._compileShader(gl.FRAGMENT_SHADER,
      `precision highp float;
      precision highp sampler2D;
      varying vec2 vUv;
      uniform sampler2D uVelocity;
      uniform sampler2D uSource;
      uniform vec2 texelSize;
      uniform vec2 dyeTexelSize;
      uniform float dt;
      uniform float dissipation;
      vec4 bilerp (sampler2D sam, vec2 uv, vec2 tsize) {
        vec2 st = uv / tsize - 0.5;
        vec2 iuv = floor(st);
        vec2 fuv = fract(st);
        vec4 a = texture2D(sam, (iuv + vec2(0.5, 0.5)) * tsize);
        vec4 b = texture2D(sam, (iuv + vec2(1.5, 0.5)) * tsize);
        vec4 c = texture2D(sam, (iuv + vec2(0.5, 1.5)) * tsize);
        vec4 d = texture2D(sam, (iuv + vec2(1.5, 1.5)) * tsize);
        return mix(mix(a, b, fuv.x), mix(c, d, fuv.x), fuv.y);
      }
      void main () {
      #ifdef MANUAL_FILTERING
        vec2 coord = vUv - dt * bilerp(uVelocity, vUv, texelSize).xy * texelSize;
        vec4 result = bilerp(uSource, coord, dyeTexelSize);
      #else
        vec2 coord = vUv - dt * texture2D(uVelocity, vUv).xy * texelSize;
        vec4 result = texture2D(uSource, coord);
      #endif
        float decay = 1.0 + dissipation * dt;
        gl_FragColor = result / decay;
      }`,
      ext.supportLinearFiltering ? null : ['MANUAL_FILTERING']
    );

    const divergenceShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision mediump float; precision mediump sampler2D;
      varying highp vec2 vUv; varying highp vec2 vL; varying highp vec2 vR; varying highp vec2 vT; varying highp vec2 vB;
      uniform sampler2D uVelocity;
      void main () {
        float L = texture2D(uVelocity, vL).x; float R = texture2D(uVelocity, vR).x;
        float T = texture2D(uVelocity, vT).y; float B = texture2D(uVelocity, vB).y;
        vec2 C = texture2D(uVelocity, vUv).xy;
        if (vL.x < 0.0) { L = -C.x; } if (vR.x > 1.0) { R = -C.x; }
        if (vT.y > 1.0) { T = -C.y; } if (vB.y < 0.0) { B = -C.y; }
        gl_FragColor = vec4(0.5 * (R - L + T - B), 0.0, 0.0, 1.0);
      }`);

    const curlShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision mediump float; precision mediump sampler2D;
      varying highp vec2 vUv; varying highp vec2 vL; varying highp vec2 vR; varying highp vec2 vT; varying highp vec2 vB;
      uniform sampler2D uVelocity;
      void main () {
        float L = texture2D(uVelocity, vL).y; float R = texture2D(uVelocity, vR).y;
        float T = texture2D(uVelocity, vT).x; float B = texture2D(uVelocity, vB).x;
        gl_FragColor = vec4(0.5 * (R - L - T + B), 0.0, 0.0, 1.0);
      }`);

    const vorticityShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision highp float; precision highp sampler2D;
      varying vec2 vUv; varying vec2 vL; varying vec2 vR; varying vec2 vT; varying vec2 vB;
      uniform sampler2D uVelocity; uniform sampler2D uCurl;
      uniform float curl; uniform float dt;
      void main () {
        float L = texture2D(uCurl, vL).x; float R = texture2D(uCurl, vR).x;
        float T = texture2D(uCurl, vT).x; float B = texture2D(uCurl, vB).x;
        float C = texture2D(uCurl, vUv).x;
        vec2 force = 0.5 * vec2(abs(T) - abs(B), abs(R) - abs(L));
        force /= length(force) + 0.0001;
        force *= curl * C; force.y *= -1.0;
        vec2 velocity = texture2D(uVelocity, vUv).xy + force * dt;
        velocity = min(max(velocity, -1000.0), 1000.0);
        gl_FragColor = vec4(velocity, 0.0, 1.0);
      }`);

    const pressureBoundaryClamp = `
        bool needsBoundaryClamp = vL.x < 0.0 || vR.x > 1.0 || vT.y > 1.0 || vB.y < 0.0;
        if (needsBoundaryClamp) {
          float centerPressure = texture2D(uPressure, vUv).x;
          if (vL.x < 0.0) { leftPressure = centerPressure; }
          if (vR.x > 1.0) { rightPressure = centerPressure; }
          if (vT.y > 1.0) { topPressure = centerPressure; }
          if (vB.y < 0.0) { bottomPressure = centerPressure; }
        }`;

    const pressureShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision mediump float; precision mediump sampler2D;
      varying highp vec2 vUv; varying highp vec2 vL; varying highp vec2 vR; varying highp vec2 vT; varying highp vec2 vB;
      uniform sampler2D uPressure; uniform sampler2D uDivergence;
      void main () {
        float leftPressure = texture2D(uPressure, vL).x; float rightPressure = texture2D(uPressure, vR).x;
        float topPressure = texture2D(uPressure, vT).x; float bottomPressure = texture2D(uPressure, vB).x;
${pressureBoundaryClamp}
        float divergence = texture2D(uDivergence, vUv).x;
        gl_FragColor = vec4((leftPressure + rightPressure + bottomPressure + topPressure - divergence) * 0.25, 0.0, 0.0, 1.0);
      }`);

    const gradientSubtractShader = this._compileShader(gl.FRAGMENT_SHADER, `
      precision mediump float; precision mediump sampler2D;
      varying highp vec2 vUv; varying highp vec2 vL; varying highp vec2 vR; varying highp vec2 vT; varying highp vec2 vB;
      uniform sampler2D uPressure; uniform sampler2D uVelocity;
      void main () {
        float leftPressure = texture2D(uPressure, vL).x; float rightPressure = texture2D(uPressure, vR).x;
        float topPressure = texture2D(uPressure, vT).x; float bottomPressure = texture2D(uPressure, vB).x;
${pressureBoundaryClamp}
        vec2 velocity = texture2D(uVelocity, vUv).xy - vec2(rightPressure - leftPressure, topPressure - bottomPressure);
        gl_FragColor = vec4(velocity, 0.0, 1.0);
      }`);

    this._setupBlit();

    this.blurProgram             = new _Program(gl, this._blurVertexShader, blurShader);
    this.copyProgram             = new _Program(gl, this._baseVertexShader, copyShader);
    this.clearProgram            = new _Program(gl, this._baseVertexShader, clearShader);
    this.bloomPrefilterProgram   = new _Program(gl, this._baseVertexShader, bloomPrefilterShader);
    this.bloomBlurProgram        = new _Program(gl, this._baseVertexShader, bloomBlurShader);
    this.bloomFinalProgram       = new _Program(gl, this._baseVertexShader, bloomFinalShader);
    this.sunraysMaskProgram      = new _Program(gl, this._baseVertexShader, sunraysMaskShader);
    this.sunraysProgram          = new _Program(gl, this._baseVertexShader, sunraysShader);
    this.splatProgram            = new _Program(gl, this._baseVertexShader, splatShader);
    this.advectionProgram        = new _Program(gl, this._baseVertexShader, advectionShader);
    this.divergenceProgram       = new _Program(gl, this._baseVertexShader, divergenceShader);
    this.curlProgram             = new _Program(gl, this._baseVertexShader, curlShader);
    this.vorticityProgram        = new _Program(gl, this._baseVertexShader, vorticityShader);
    this.pressureProgram         = new _Program(gl, this._baseVertexShader, pressureShader);
    this.gradientSubtractProgram = new _Program(gl, this._baseVertexShader, gradientSubtractShader);

    // ditherTextureUrl option lets callers load the PNG from an external URL
    this.ditheringTexture = this._createTextureAsync(options.ditherTextureUrl ?? 'LDR_LLL1_0.png');
    this.displayMaterial  = new _Material(gl, this._baseVertexShader, displayShaderSource, this);
  }

  _setupBlit () {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, -1, 1, 1, 1, 1, -1]), gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array([0, 1, 2, 0, 2, 3]), gl.STATIC_DRAW);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.enableVertexAttribArray(0);
  }

  _blit (target, clear = false) {
    const gl = this.gl;
    if (target == null) {
      gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    } else {
      gl.viewport(0, 0, target.width, target.height);
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
    }
    if (clear) { gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); }
    gl.drawElements(gl.TRIANGLES, 6, gl.UNSIGNED_SHORT, 0);
  }

  _initFramebuffers () {
    const { gl, ext, config } = this;
    const simRes = this._getResolution(config.SIM_RESOLUTION);
    const dyeRes = this._getResolution(config.DYE_RESOLUTION);
    const texType  = ext.halfFloatTexType;
    const rgba     = ext.formatRGBA;
    const rg       = ext.formatRG;
    const r        = ext.formatR;
    const filtering = ext.supportLinearFiltering ? gl.LINEAR : gl.NEAREST;

    gl.disable(gl.BLEND);

    if (this.dye == null)
      this.dye = this._createDoubleFBO(dyeRes.width, dyeRes.height, rgba.internalFormat, rgba.format, texType, filtering);
    else
      this.dye = this._resizeDoubleFBO(this.dye, dyeRes.width, dyeRes.height, rgba.internalFormat, rgba.format, texType, filtering);

    if (this.velocity == null)
      this.velocity = this._createDoubleFBO(simRes.width, simRes.height, rg.internalFormat, rg.format, texType, filtering);
    else
      this.velocity = this._resizeDoubleFBO(this.velocity, simRes.width, simRes.height, rg.internalFormat, rg.format, texType, filtering);

    this.divergence = this._createFBO(simRes.width, simRes.height, r.internalFormat, r.format, texType, gl.NEAREST);
    this.curl       = this._createFBO(simRes.width, simRes.height, r.internalFormat, r.format, texType, gl.NEAREST);
    this.pressure   = this._createDoubleFBO(simRes.width, simRes.height, r.internalFormat, r.format, texType, gl.NEAREST);
    this._initBloomFramebuffers();
    this._initSunraysFramebuffers();
  }

  _initBloomFramebuffers () {
    const { gl, ext, config } = this;
    const res      = this._getResolution(config.BLOOM_RESOLUTION);
    const texType  = ext.halfFloatTexType;
    const rgba     = ext.formatRGBA;
    const filtering = ext.supportLinearFiltering ? gl.LINEAR : gl.NEAREST;

    this.bloom = this._createFBO(res.width, res.height, rgba.internalFormat, rgba.format, texType, filtering);
    this.bloomFramebuffers = [];
    for (let i = 0; i < config.BLOOM_ITERATIONS; i++) {
      const width  = res.width  >> (i + 1);
      const height = res.height >> (i + 1);
      if (width < 2 || height < 2) break;
      this.bloomFramebuffers.push(this._createFBO(width, height, rgba.internalFormat, rgba.format, texType, filtering));
    }
  }

  _initSunraysFramebuffers () {
    const { gl, ext, config } = this;
    const res      = this._getResolution(config.SUNRAYS_RESOLUTION);
    const texType  = ext.halfFloatTexType;
    const r        = ext.formatR;
    const filtering = ext.supportLinearFiltering ? gl.LINEAR : gl.NEAREST;
    this.sunrays     = this._createFBO(res.width, res.height, r.internalFormat, r.format, texType, filtering);
    this.sunraysTemp = this._createFBO(res.width, res.height, r.internalFormat, r.format, texType, filtering);
  }

  _createFBO (w, h, internalFormat, format, type, param) {
    const gl = this.gl;
    gl.activeTexture(gl.TEXTURE0);
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, param);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, param);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, internalFormat, w, h, 0, format, type, null);
    const fbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
    gl.viewport(0, 0, w, h);
    gl.clear(gl.COLOR_BUFFER_BIT);
    return {
      texture, fbo, width: w, height: h,
      texelSizeX: 1.0 / w, texelSizeY: 1.0 / h,
      attach (id) {
        gl.activeTexture(gl.TEXTURE0 + id);
        gl.bindTexture(gl.TEXTURE_2D, texture);
        return id;
      }
    };
  }

  _createDoubleFBO (w, h, internalFormat, format, type, param) {
    let fbo1 = this._createFBO(w, h, internalFormat, format, type, param);
    let fbo2 = this._createFBO(w, h, internalFormat, format, type, param);
    return {
      width: w, height: h,
      texelSizeX: fbo1.texelSizeX, texelSizeY: fbo1.texelSizeY,
      get read  () { return fbo1; }, set read  (v) { fbo1 = v; },
      get write () { return fbo2; }, set write (v) { fbo2 = v; },
      swap () { const t = fbo1; fbo1 = fbo2; fbo2 = t; }
    };
  }

  _resizeFBO (target, w, h, internalFormat, format, type, param) {
    const newFBO = this._createFBO(w, h, internalFormat, format, type, param);
    this.copyProgram.bind();
    this.gl.uniform1i(this.copyProgram.uniforms.uTexture, target.attach(0));
    this._blit(newFBO);
    return newFBO;
  }

  _resizeDoubleFBO (target, w, h, internalFormat, format, type, param) {
    if (target.width === w && target.height === h) return target;
    target.read  = this._resizeFBO(target.read, w, h, internalFormat, format, type, param);
    target.write = this._createFBO(w, h, internalFormat, format, type, param);
    target.width = w; target.height = h;
    target.texelSizeX = 1.0 / w; target.texelSizeY = 1.0 / h;
    return target;
  }

  _applyBloom (source, destination) {
    const { gl, config } = this;
    if (!this.bloomFramebuffers || this.bloomFramebuffers.length < 2) return;
    let last = destination;
    gl.disable(gl.BLEND);
    this.bloomPrefilterProgram.bind();
    const knee   = config.BLOOM_THRESHOLD * config.BLOOM_SOFT_KNEE + 0.0001;
    const curve0 = config.BLOOM_THRESHOLD - knee;
    const curve1 = knee * 2.0;
    const curve2 = 0.25 / knee;
    gl.uniform3f(this.bloomPrefilterProgram.uniforms.curve, curve0, curve1, curve2);
    gl.uniform1f(this.bloomPrefilterProgram.uniforms.threshold, config.BLOOM_THRESHOLD);
    gl.uniform1i(this.bloomPrefilterProgram.uniforms.uTexture, source.attach(0));
    this._blit(last);
    this.bloomBlurProgram.bind();
    for (let i = 0; i < this.bloomFramebuffers.length; i++) {
      const dest = this.bloomFramebuffers[i];
      gl.uniform2f(this.bloomBlurProgram.uniforms.texelSize, last.texelSizeX, last.texelSizeY);
      gl.uniform1i(this.bloomBlurProgram.uniforms.uTexture, last.attach(0));
      this._blit(dest);
      last = dest;
    }
    gl.blendFunc(gl.ONE, gl.ONE);
    gl.enable(gl.BLEND);
    for (let i = this.bloomFramebuffers.length - 2; i >= 0; i--) {
      const baseTex = this.bloomFramebuffers[i];
      gl.uniform2f(this.bloomBlurProgram.uniforms.texelSize, last.texelSizeX, last.texelSizeY);
      gl.uniform1i(this.bloomBlurProgram.uniforms.uTexture, last.attach(0));
      gl.viewport(0, 0, baseTex.width, baseTex.height);
      this._blit(baseTex);
      last = baseTex;
    }
    gl.disable(gl.BLEND);
    this.bloomFinalProgram.bind();
    gl.uniform2f(this.bloomFinalProgram.uniforms.texelSize, last.texelSizeX, last.texelSizeY);
    gl.uniform1i(this.bloomFinalProgram.uniforms.uTexture, last.attach(0));
    gl.uniform1f(this.bloomFinalProgram.uniforms.intensity, config.BLOOM_INTENSITY);
    this._blit(destination);
  }

  _applySunrays (source, mask, destination) {
    const { gl, config } = this;
    gl.disable(gl.BLEND);
    this.sunraysMaskProgram.bind();
    gl.uniform1i(this.sunraysMaskProgram.uniforms.uTexture, source.attach(0));
    this._blit(mask);
    this.sunraysProgram.bind();
    gl.uniform1f(this.sunraysProgram.uniforms.weight, config.SUNRAYS_WEIGHT);
    gl.uniform1i(this.sunraysProgram.uniforms.uTexture, mask.attach(0));
    this._blit(destination);
  }

  _blur (target, temp, iterations) {
    const gl = this.gl;
    this.blurProgram.bind();
    for (let i = 0; i < iterations; i++) {
      gl.uniform2f(this.blurProgram.uniforms.texelSize, target.texelSizeX, 0.0);
      gl.uniform1i(this.blurProgram.uniforms.uTexture, target.attach(0));
      this._blit(temp);
      gl.uniform2f(this.blurProgram.uniforms.texelSize, 0.0, target.texelSizeY);
      gl.uniform1i(this.blurProgram.uniforms.uTexture, temp.attach(0));
      this._blit(target);
    }
  }

  _drawDisplay (target) {
    const { gl, config } = this;
    const width  = target == null ? gl.drawingBufferWidth  : target.width;
    const height = target == null ? gl.drawingBufferHeight : target.height;
    this.displayMaterial.bind();
    if (config.SHADING)
      gl.uniform2f(this.displayMaterial.uniforms.texelSize, 1.0 / width, 1.0 / height);
    gl.uniform1i(this.displayMaterial.uniforms.uTexture, this.dye.read.attach(0));
    if (config.BLOOM && this.bloom && this.ditheringTexture) {
      gl.uniform1i(this.displayMaterial.uniforms.uBloom, this.bloom.attach(1));
      gl.uniform1i(this.displayMaterial.uniforms.uDithering, this.ditheringTexture.attach(2));
      const scale = this._getTextureScale(this.ditheringTexture, width, height);
      gl.uniform2f(this.displayMaterial.uniforms.ditherScale, scale.x, scale.y);
    }
    if (config.SUNRAYS && this.sunrays)
      gl.uniform1i(this.displayMaterial.uniforms.uSunrays, this.sunrays.attach(3));
    this._blit(target);
  }

  _updateKeywords () {
    const displayKeywords = [];
    if (this.config.SHADING)  displayKeywords.push('SHADING');
    if (this.config.BLOOM)    displayKeywords.push('BLOOM');
    if (this.config.SUNRAYS)  displayKeywords.push('SUNRAYS');
    this.displayMaterial.setKeywords(displayKeywords);
  }

  _getResolution (resolution) {
    const gl = this.gl;
    let aspectRatio = gl.drawingBufferWidth / gl.drawingBufferHeight;
    if (aspectRatio < 1) aspectRatio = 1.0 / aspectRatio;
    const min = Math.round(resolution);
    const max = Math.round(resolution * aspectRatio);
    return gl.drawingBufferWidth > gl.drawingBufferHeight
      ? { width: max, height: min }
      : { width: min, height: max };
  }

  _correctRadius (radius) {
    const aspectRatio = this.canvas.width / this.canvas.height;
    if (aspectRatio > 1) radius *= aspectRatio;
    return radius;
  }

  _createTextureAsync (url) {
    const gl = this.gl;
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, 1, 1, 0, gl.RGB, gl.UNSIGNED_BYTE, new Uint8Array([255, 255, 255]));
    const out = {
      texture, width: 1, height: 1,
      attach (id) {
        gl.activeTexture(gl.TEXTURE0 + id);
        gl.bindTexture(gl.TEXTURE_2D, texture);
        return id;
      }
    };
    const image = new Image();
    image.crossOrigin = 'anonymous';
    image.onload = () => {
      out.width = image.width;
      out.height = image.height;
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, image);
    };
    image.src = url;
    return out;
  }

  _getTextureScale (texture, width, height) {
    return { x: width / texture.width, y: height / texture.height };
  }

  _compileShader (type, source, keywords) {
    const gl = this.gl;
    if (keywords) source = keywords.map(k => '#define ' + k).join('\n') + '\n' + source;
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS))
      console.error('Shader compile error:', gl.getShaderInfoLog(shader));
    return shader;
  }
}

// ── Helper classes ────────────────────────────────────────────────────────────

class _Program {
  constructor (gl, vertexShader, fragmentShader) {
    this.gl = gl;
    this.program = gl.createProgram();
    gl.attachShader(this.program, vertexShader);
    gl.attachShader(this.program, fragmentShader);
    gl.linkProgram(this.program);
    if (!gl.getProgramParameter(this.program, gl.LINK_STATUS))
      console.error('Program link error:', gl.getProgramInfoLog(this.program));
    this.uniforms = _getUniforms(gl, this.program);
  }
  bind () { this.gl.useProgram(this.program); }
}

class _Material {
  constructor (gl, vertexShader, fragmentShaderSource, sim) {
    this.gl = gl;
    this.vertexShader = vertexShader;
    this.fragmentShaderSource = fragmentShaderSource;
    this.sim = sim;
    this.programs = {};
    this.activeProgram = null;
    this.uniforms = {};
  }
  setKeywords (keywords) {
    const hash = keywords.join(',');
    if (!this.programs[hash]) {
      const src  = keywords.map(k => '#define ' + k).join('\n') + '\n' + this.fragmentShaderSource;
      const frag = this.sim._compileShader(this.gl.FRAGMENT_SHADER, src);
      this.programs[hash] = new _Program(this.gl, this.vertexShader, frag);
    }
    const prog = this.programs[hash];
    if (prog === this.activeProgram) return;
    this.uniforms = prog.uniforms;
    this.activeProgram = prog;
  }
  bind () { this.gl.useProgram(this.activeProgram.program); }
}

function _getUniforms (gl, program) {
  const uniforms = {};
  const count = gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < count; i++) {
    const name = gl.getActiveUniform(program, i).name;
    uniforms[name] = gl.getUniformLocation(program, name);
  }
  return uniforms;
}
