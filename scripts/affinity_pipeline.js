/*
affinity_pipeline.js

Kaelovun automation for the new unified Affinity (Canva-era).

Runs inside Affinity via its MCP execute_script tool. Only documented
SDK patterns are used: require('/application'), app.documents.current,
mutations through doc.executeCommand, results via console.log.

Save / close / layer-visibility APIs differ between Affinity builds,
so every function probes several strategies and ALWAYS prints one
JSON line: {"ok":true,...} or {"ok":false,...}. The Python controller
reads that line and degrades gracefully (warn + continue) instead of
ever failing a job on an Affinity API mismatch.
*/


function aoCurrentDocName()
{
    try {
        var app = require('/application').app;
        var doc = app.documents.current;
        if (!doc) {
            console.log(JSON.stringify({ ok: true, name: null }));
            return;
        }
        console.log(JSON.stringify({ ok: true, name: doc.name || doc.title || null }));
    } catch (e) {
        console.log(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
    }
}


function aoProbe()
{
    // Reports which automation surface this Affinity build has, so the
    // controller (and the user, via the log) can see what will work.
    // NOTE: doc members live on the prototype — read them on the
    // instance (doc.sessionUuid), never on Object.getPrototypeOf(doc).
    try {
        var app = require('/application').app;
        var doc = app.documents.current;
        var info = { ok: true, hasDoc: !!doc, docName: null, can: {} };
        if (doc) {
            try { info.docName = doc.title || doc.name || null; } catch (e) {}
            try { info.sessionUuid = doc.sessionUuid || null; } catch (e) {}
            info.can.save = (typeof doc.save === 'function');
            info.can.close = (typeof doc.close === 'function');
        }
        info.can.executeCommand = !!(doc && typeof doc.executeCommand === 'function');
        var docs = app.documents;
        info.can.docsOpen = (typeof docs.open === 'function');
        info.can.docsClose = (typeof docs.close === 'function');
        console.log(JSON.stringify(info));
    } catch (e) {
        console.log(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
    }
}


function aoSessionUuid()
{
    // The render_* tools need the open document's session UUID.
    try {
        var app = require('/application').app;
        var doc = app.documents.current;
        if (!doc) {
            console.log(JSON.stringify({ ok: false, error: 'no open document' }));
            return;
        }
        console.log(JSON.stringify({ ok: true, sessionUuid: doc.sessionUuid }));
    } catch (e) {
        console.log(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
    }
}


function aoHideVisibleLayers()
{
    // A single locked-visible layer keeps the file big, and one
    // selectAll+hide pass can leave exactly that behind (locked
    // layers skip the hide). So: unlock everything first, then hide,
    // and repeat up to 3 passes so layers unlocked in pass N are
    // hidden in pass N+1. Every probe is guarded — unknown APIs on a
    // given build just fall through to the next strategy.
    try {
        var app = require('/application').app;
        var doc = app.documents.current;
        if (!doc) {
            console.log(JSON.stringify({ ok: false, error: 'no open document' }));
            return;
        }
        var unlocked = true;
        var hidSomething = false;
        var lastError = null;
        for (var pass = 0; pass < 3; pass++) {
            try { doc.selectAll(); } catch (e) { lastError = String(e && e.message || e); continue; }
            try {
                if (typeof doc.unlockAll === 'function') { doc.unlockAll(); }
            } catch (e) {}
            try { doc.unlockSelection(); }
            catch (e) {
                unlocked = false;
                lastError = String(e && e.message || e);
            }
            try {
                doc.hideSelection();
                hidSomething = true;
            } catch (e) { lastError = String(e && e.message || e); }
        }
        try { if (typeof doc.clearSelection === 'function') { doc.clearSelection(); } } catch (e) {}
        try { if (typeof doc.deselectAll === 'function') { doc.deselectAll(); } } catch (e) {}
        console.log(JSON.stringify({ ok: true, method: 'selectAll+unlock+hide x3', unlocked: unlocked, hid: hidSomething, note: lastError }));
    } catch (e) {
        console.log(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
    }
}


function aoSave()
{
    // Verified on 3.2.1: doc.save() exists but PSD imports fail with
    // SAVE_TO_TEMPORARY_ARCHIVE_ERROR (no PSD write-back). Native
    // .afphoto/.afdesign saves may succeed — strategies cover both.
    try {
        var app = require('/application').app;
        var doc = app.documents.current;
        if (!doc) {
            console.log(JSON.stringify({ ok: false, error: 'no open document' }));
            return;
        }
        var tried = [];
        var strategies = [
            function () { doc.save(); },
            function () { doc.saveToFile(); },
            function () { app.documents.save(doc); },
            function () { app.saveActiveDocument(); }
        ];
        for (var i = 0; i < strategies.length; i++) {
            try {
                strategies[i]();
                console.log(JSON.stringify({ ok: true, strategy: i }));
                return;
            } catch (e) { tried.push(i + ':' + String(e && e.message || e)); }
        }
        console.log(JSON.stringify({ ok: false, tried: tried }));
    } catch (e) {
        console.log(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
    }
}


function aoClose()
{
    // Verified on 3.2.1: close()/closeAsync() throw NOT_IMPLEMENTED
    // (Canva's own SDK tests carry "waiting for close to be fixed").
    // Strategies are kept so future builds light up with no code change.
    try {
        var app = require('/application').app;
        var doc = app.documents.current;
        if (!doc) {
            console.log(JSON.stringify({ ok: true, alreadyClosed: true }));
            return;
        }
        var tried = [];
        var strategies = [
            function () { doc.close(); },
            function () { doc.closeWithoutSaving(); },
            function () { app.documents.close(doc); },
            function () { app.closeActiveDocument(); }
        ];
        for (var i = 0; i < strategies.length; i++) {
            try {
                strategies[i]();
                console.log(JSON.stringify({ ok: true, strategy: i }));
                return;
            } catch (e) { tried.push(i + ':' + String(e && e.message || e)); }
        }
        console.log(JSON.stringify({ ok: false, tried: tried }));
    } catch (e) {
        console.log(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
    }
}
