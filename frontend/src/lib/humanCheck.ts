/**
 * Solving the sign-in proof of work, in the browser.
 *
 * The server asks for a nonce whose `sha256(salt:nonce)` begins with a number
 * of zero bits. Verifying that is one hash; finding it is 2^d on average. That
 * asymmetry is the whole mechanism, and this side is the expensive half — by
 * design, because the expense is what a guessing loop pays too.
 *
 * **Why SHA-256 is implemented here rather than called from `crypto.subtle`.**
 * The browser's own digest is asynchronous: one promise per hash. Sixty-five
 * thousand of them — the cheapest difficulty the server issues — take seconds
 * of promise scheduling to compute milliseconds of hashing. A synchronous
 * implementation does the same work in about a tenth of a second.
 *
 * **Why it yields.** At the hardest rung the search is around a million
 * hashes. Run straight through, that is a second or so of frozen page, which
 * reads as a crash. The loop hands control back every few thousand attempts,
 * so the button can keep saying what it is doing.
 *
 * The string being hashed is `${salt}:${nonce}` and must stay exactly that.
 * `app/services/human_check.py` has the other half, and a disagreement of one
 * colon between them produces a login that rejects every correct password
 * while blaming the password.
 */

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
  0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
  0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
  0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
  0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
  0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

/** SHA-256 of a byte array, returned as the first four bytes of the digest.
 *
 * Only the first four are returned because only they are read: the server asks
 * for at most 22 leading zero bits, and no answer can depend on byte five. */
function sha256Prefix(message: Uint8Array): number {
  const bitLength = message.length * 8;
  // Message, the 0x80 terminator, padding to 56 mod 64, and an 8-byte length.
  const paddedLength = (((message.length + 9 + 63) / 64) | 0) * 64;
  const block = new Uint8Array(paddedLength);
  block.set(message);
  block[message.length] = 0x80;
  const view = new DataView(block.buffer);
  // Lengths here are far below 2^32 bits, so the high word is always zero.
  view.setUint32(paddedLength - 4, bitLength >>> 0, false);

  let h0 = 0x6a09e667,
    h1 = 0xbb67ae85,
    h2 = 0x3c6ef372,
    h3 = 0xa54ff53a,
    h4 = 0x510e527f,
    h5 = 0x9b05688c,
    h6 = 0x1f83d9ab,
    h7 = 0x5be0cd19;

  const w = new Uint32Array(64);

  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let i = 0; i < 16; i += 1) w[i] = view.getUint32(offset + i * 4, false);
    for (let i = 16; i < 64; i += 1) {
      const a = w[i - 15];
      const b = w[i - 2];
      const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
      const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }

    let a = h0,
      b = h1,
      c = h2,
      d = h3,
      e = h4,
      f = h5,
      g = h6,
      h = h7;

    for (let i = 0; i < 64; i += 1) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K[i] + w[i]) | 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) | 0;

      h = g;
      g = f;
      f = e;
      e = (d + t1) | 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) | 0;
    }

    h0 = (h0 + a) | 0;
    h1 = (h1 + b) | 0;
    h2 = (h2 + c) | 0;
    h3 = (h3 + d) | 0;
    h4 = (h4 + e) | 0;
    h5 = (h5 + f) | 0;
    h6 = (h6 + g) | 0;
    h7 = (h7 + h) | 0;
  }

  return h0 >>> 0;
}

/** How many zero bits the digest starts with, from its first word. */
export function leadingZeroBits(firstWord: number): number {
  if (firstWord === 0) return 32;
  return Math.clz32(firstWord);
}

export interface Challenge {
  challenge_id: string;
  salt: string;
  difficulty: number;
  required: boolean;
}

/**
 * Find a nonce that satisfies the challenge.
 *
 * `onProgress` is called with the attempt count so a caller can say something
 * while it works. `limit` bounds the search: a difficulty far above what the
 * server issues should end as a reported failure, not as a tab that never
 * comes back.
 */
export async function solve(
  salt: string,
  difficulty: number,
  options: { onProgress?: (attempts: number) => void; limit?: number } = {},
): Promise<number> {
  const limit = options.limit ?? 1 << 26;
  const encoder = new TextEncoder();
  const prefix = `${salt}:`;
  // Yielding every few thousand attempts keeps the page responsive without
  // making the scheduler the dominant cost.
  const batch = 4096;

  for (let nonce = 0; nonce < limit; nonce += 1) {
    if (leadingZeroBits(sha256Prefix(encoder.encode(prefix + nonce))) >= difficulty) {
      return nonce;
    }
    if (nonce % batch === batch - 1) {
      options.onProgress?.(nonce + 1);
      await new Promise((resume) => setTimeout(resume, 0));
    }
  }

  throw new Error(`no nonce found below ${limit} for difficulty ${difficulty}`);
}

/**
 * Ask for a challenge and solve it if the server says one is needed.
 *
 * Returns the fields to merge into the sign-in body — empty when no proof is
 * being asked for, which is the ordinary case and the first sign-in anybody
 * ever makes.
 *
 * Asked *before* the attempt rather than after a refusal. The server records a
 * missing proof as a failed attempt, so retrying after a rejection would spend
 * two attempts per sign-in and reach the cooldown twice as fast.
 */
export async function proofFor(
  email: string,
  onProgress?: (attempts: number) => void,
): Promise<{ challenge_id?: string; nonce?: number }> {
  const response = await fetch(
    `/api/v1/session/challenge?email=${encodeURIComponent(email)}`,
    { cache: "no-store" },
  );
  if (!response.ok) return {};

  const challenge = (await response.json()) as Challenge;
  if (!challenge.required) return {};

  const nonce = await solve(challenge.salt, challenge.difficulty, { onProgress });
  return { challenge_id: challenge.challenge_id, nonce };
}
