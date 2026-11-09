// Music Hub for YouTube: the go-between for the YouTube tab and the coach on this PC.
//
// The tab's script can't call the coach itself (a YouTube page reaching into the local
// network gets blocked or asks for permission), so it sends each command here and this
// worker posts it to http://127.0.0.1:<port>/cmd/<name>. The coach's port is 8765, or one
// of the nine after it when that was busy; the one that answers /version is remembered.

const FIRST_PORT = 8765, PORTS = 10;
// The version tells the coach's YouTube tab this copy is loaded and whether it's the latest.
const HEADERS = {'Content-Type': 'application/json', 'X-Piano-Coach-Extension': chrome.runtime.getManifest().version};
let base = null;

async function answers(url) {
  try {
    const res = await fetch(url + 'version', {signal: AbortSignal.timeout(800), cache: 'no-store'});
    return res.ok && 'started' in await res.json();
  } catch (e) {
    return false;
  }
}

async function findCoach() {
  if (base && await answers(base)) return base;
  base = null;
  for (let port = FIRST_PORT; port < FIRST_PORT + PORTS; port++) {
    const url = `http://127.0.0.1:${port}/`;
    if (await answers(url)) return (base = url);
  }
  return null;
}

async function post(name, body) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const url = base || await findCoach();
    if (!url) return {offline: true};
    try {
      const res = await fetch(url + 'cmd/' + name, {method: 'POST', headers: HEADERS, body: JSON.stringify(body || {}),
                                                    cache: 'no-store'});
      return await res.json();
    } catch (e) {
      base = null;  // the coach restarted, maybe on another port: look again once
    }
  }
  return {offline: true};
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || !msg.cmd) return false;
  post(msg.cmd, msg.body).then(reply);
  return true;  // the reply comes later
});
