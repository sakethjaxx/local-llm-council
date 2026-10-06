const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');
const modules = path.join(__dirname, 'frontend/node_modules');
const target = path.join(root, 'src/council/static/vendor');
const libraries = [
  ['dompurify', 'dist/purify.min.js', 'purify.min.js'],
  ['marked', 'lib/marked.umd.js', 'marked.umd.js'],
  ['vis-network', 'standalone/umd/vis-network.min.js', 'vis-network.min.js'],
];

if (!process.argv.includes('--check')) fs.mkdirSync(target, { recursive: true });
for (const [name, source, filename] of libraries) {
  const sourceFile = path.join(modules, name, source);
  const targetFile = path.join(target, filename);
  const licenseSource = ['LICENSE', 'LICENSE.md', 'LICENSE-MIT'].map(file => path.join(modules, name, file))
    .find(file => fs.existsSync(file));
  assert(licenseSource, `Missing license for ${name}`);
  const licenseTarget = path.join(target, `LICENSE.${name}.txt`);
  if (process.argv.includes('--check')) {
    assert(fs.readFileSync(sourceFile).equals(fs.readFileSync(targetFile)), `Vendored ${name} differs from pinned package`);
    assert(fs.readFileSync(licenseSource).equals(fs.readFileSync(licenseTarget)), `License differs for ${name}`);
  } else {
    fs.copyFileSync(sourceFile, targetFile);
    fs.copyFileSync(licenseSource, licenseTarget);
  }
  console.log(`${process.argv.includes('--check') ? 'Verified' : 'Vendored'} ${name}`);
}
