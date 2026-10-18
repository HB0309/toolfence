/* live.js — L-3 live panel logic
 * Plain JS, relative URLs only, textContent only, no local storage.
 */
(function () {
  'use strict';

  var liveKey = null;
  var pollInterval = null;

  var panel   = document.getElementById('live-panel');
  var liveOff = document.getElementById('live-off');
  var keyInput   = document.getElementById('live-key');
  var keyTest    = document.getElementById('live-key-test');
  var keyMsg     = document.getElementById('live-key-msg');
  var guardSel   = document.getElementById('live-guard');
  var defenseSel = document.getElementById('live-defense');
  var promptTA   = document.getElementById('live-prompt');
  var sendBtn    = document.getElementById('live-send');
  var cardDiv    = document.getElementById('live-card');
  var cardText   = document.getElementById('live-card-text');
  var allowBtn   = document.getElementById('live-allow');
  var declineBtn = document.getElementById('live-decline');
  var outPre     = document.getElementById('live-out');

  /* Toggle panel on LIVE button click */
  document.getElementById('f-live').addEventListener('click', function () {
    panel.classList.toggle('d-none');
  });

  /* On load: check whether live mode is enabled on this server */
  fetch('api/live/status')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data && data.enabled) {
        liveOff.classList.add('d-none');
        keyInput.disabled = false;
        keyTest.disabled = false;
      }
      /* else: leave live-off visible, all inputs stay disabled */
    })
    .catch(function () {
      /* fetch failed — keep live-off visible, everything disabled */
    });

  /* Re-lock prompt whenever the key field is edited */
  keyInput.addEventListener('input', function () {
    liveKey = null;
    promptTA.disabled = true;
    sendBtn.disabled = true;
  });

  /* Test key button */
  keyTest.addEventListener('click', function () {
    var key = keyInput.value;
    fetch('api/live/key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: key })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        keyMsg.textContent = data.message || '';
        if (data.ok) {
          liveKey = key;
          promptTA.disabled = false;
          sendBtn.disabled = false;
        } else {
          liveKey = null;
          promptTA.disabled = true;
          sendBtn.disabled = true;
        }
      })
      .catch(function () {
        keyMsg.textContent = 'Request failed';
        liveKey = null;
      });
  });

  /* Send button */
  sendBtn.addEventListener('click', function () {
    sendBtn.disabled = true;
    outPre.textContent = 'Running\u2026';

    /* Poll for pending confirm cards */
    pollInterval = setInterval(function () {
      fetch('api/live/pending')
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data && data.pending) {
            var p = data.pending;
            cardText.textContent = (p.text || '') + ' [' + (p.tool || '') + ']';
            cardDiv.classList.remove('d-none');
          } else {
            cardDiv.classList.add('d-none');
          }
        })
        .catch(function () {});
    }, 1000);

    var prompt  = promptTA.value;
    var guard   = guardSel.value === 'true';
    var defense = defenseSel.value;

    fetch('api/live/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: liveKey, prompt: prompt, guard: guard, defense: defense })
    })
      .then(function (r) {
        clearInterval(pollInterval);
        pollInterval = null;
        cardDiv.classList.add('d-none');
        sendBtn.disabled = false;
        if (!r.ok) {
          return r.text().then(function (t) {
            outPre.textContent = 'HTTP ' + r.status + '\n' + t;
          });
        }
        return r.json().then(function (data) {
          var trace = data.trace || data;
          var lines = [];
          lines.push('status: ' + (trace.status || ''));
          lines.push('final_reply: ' + (trace.final_reply || ''));
          var calls = trace.tool_calls || [];
          for (var i = 0; i < calls.length; i++) {
            var c = calls[i];
            var detail = c.error || c.result || '';
            if (typeof detail !== 'string') {
              detail = JSON.stringify(detail);
            }
            if (detail.length > 300) {
              detail = detail.slice(0, 300) + '\u2026';
            }
            lines.push((c.name || '') + ' | ' + (c.guard_decision || '') + ' | ' + detail);
          }
          outPre.textContent = lines.join('\n');
        });
      })
      .catch(function (err) {
        clearInterval(pollInterval);
        pollInterval = null;
        cardDiv.classList.add('d-none');
        sendBtn.disabled = false;
        outPre.textContent = 'Request failed: ' + err;
      });
  });

  /* Allow / Decline buttons */
  allowBtn.addEventListener('click', function () {
    fetch('api/live/decide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved: true })
    }).catch(function () {});
    cardDiv.classList.add('d-none');
  });

  declineBtn.addEventListener('click', function () {
    fetch('api/live/decide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved: false })
    }).catch(function () {});
    cardDiv.classList.add('d-none');
  });

}());
