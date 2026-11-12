// Check that the web flasher (site/tr8patch.js) builds the same file as tools/tr8patch.py.
//
//   node tests/site_check.mjs TR8_UPD.BIN-or-tr8_sys_v161.zip work/TR8_UPD_<name>.BIN...
//
// Each reference file name gives the patch: work/TR8_UPD_poly.BIN -> poly.
import { readFileSync } from "node:fs";
import { build, extractUpdate, PatchError } from "../site/tr8patch.js";

const [input, ...refs] = process.argv.slice(2);
const manifest = JSON.parse(readFileSync(new URL("../site/patches.json", import.meta.url)));
const img = await extractUpdate(new Uint8Array(readFileSync(input)));
let fails = 0;
const expect = (name, ok, detail = "") => {
  fails += !ok;
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${ok ? "" : "  " + detail}`);
};
for (const ref of refs) {
  const name = ref.match(/TR8_UPD_(.+)\.BIN$/)[1].replace(/_/g, "-");
  const want = new Uint8Array(readFileSync(ref));
  const got = await build(img, manifest, [name]);
  const diff = got.findIndex((v, k) => v !== want[k]);
  expect(`${name}: same file as tr8patch.py`, got.length === want.length && diff < 0, `first difference at 0x${diff.toString(16)}`);
}
const rejects = async (label, fn) => {
  try { await fn(); expect(label, false, "no error"); }
  catch (e) { expect(label, e instanceof PatchError, String(e)); }
};
await rejects("patched file is refused as input", async () => {
  const patched = await build(img, manifest, [Object.keys(manifest.patches)[0]]);
  await build(patched, manifest, ["poly"]);
});
await rejects("motion + poly cannot be combined", () => build(img, manifest, ["motion", "poly"]));
await rejects("truncated file is refused", () => build(img.subarray(0, 0x200000), manifest, ["poly"]));
const bad = Uint8Array.from(img); bad[0x30100] ^= 1;
await rejects("corrupted file is refused", () => build(bad, manifest, ["poly"]));
console.log(fails ? "FAILED" : "ALL PASS");
process.exit(fails ? 1 : 0);
