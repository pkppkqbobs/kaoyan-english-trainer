// Extract only the legacy home page's data literal, never its application code.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
const root = process.argv[2] || process.cwd();
const source = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const literal = source.match(/const BANK\s*=\s*(\[[\s\S]*?\n\]);/);
if (!literal) throw new Error('Unknown legacy home bank format');
const questions = vm.runInNewContext('(' + literal[1] + ')', Object.create(null), {timeout:1000});
if (!Array.isArray(questions)) throw new Error('Home bank must be an array');
process.stdout.write(JSON.stringify(questions));
