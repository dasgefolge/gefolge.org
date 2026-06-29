document.querySelectorAll('.datetime').forEach(function(dateTime) {
    var timestamp = new Date(parseInt(dateTime.dataset.timestamp));
    var longFormat = dateTime.dataset.long == 'true';
    if ('timezone' in dateTime.dataset) {
        // preserve specified timezone but otherwise format according to user locale
        dateTime.textContent = timestamp.toLocaleString([], {
            dateStyle: longFormat ? 'full' : 'medium',
            timeStyle: longFormat ? 'full' : 'short',
            timeZone: dateTime.dataset.timezone,
        });
        var timezone = 'unbekannte Zeitzone';
        Intl.DateTimeFormat([], {timeZoneName: 'long', timeZone: dateTime.dataset.timezone}).formatToParts(timestamp).forEach(function(part) {
            if (part.type === 'timeZoneName') {
                timezone = part.value;
            }
        });
        dateTime.setAttribute('title', timezone);
    } else {
        // format according to user locale including timezone
        dateTime.textContent = timestamp.toLocaleString([], {
            dateStyle: longFormat ? 'full' : 'medium',
            timeStyle: longFormat ? 'full' : 'short',
        });
        var timezone = 'unbekannte Zeitzone';
        Intl.DateTimeFormat([], {timeZoneName: 'long'}).formatToParts(timestamp).forEach(function(part) {
            if (part.type === 'timeZoneName') {
                timezone = part.value;
            }
        });
        dateTime.setAttribute('title', timezone);
        dateTime.dataset.timezone = 'local'; // set data-timezone to some value to remove the dotted underline
    }
});

document.querySelectorAll('.daterange').forEach(function(dateRange) {
    var start = new Date(parseInt(dateRange.dataset.start));
    var end = new Date(parseInt(dateRange.dataset.end));
    if ('timezone' in dateRange.dataset) {
        // preserve specified timezone but otherwise format according to user locale
        dateRange.textContent = Intl.DateTimeFormat([], {dateStyle: 'long', timeZone: dateRange.dataset.timezone}).formatRange(start, end);
        var timezone = 'unbekannte Zeitzone';
        Intl.DateTimeFormat([], {timeZoneName: 'long', timeZone: dateRange.dataset.timezone}).formatToParts(start).forEach(function(part) {
            if (part.type === 'timeZoneName') {
                timezone = part.value;
            }
        });
        dateRange.setAttribute('title', timezone);
    } else {
        // format according to user locale including timezone
        dateRange.textContent = Intl.DateTimeFormat([], {dateStyle: 'long'}).formatRange(start, end);
        var timezone = 'unbekannte Zeitzone';
        Intl.DateTimeFormat([], {timeZoneName: 'long'}).formatToParts(start).forEach(function(part) {
            if (part.type === 'timeZoneName') {
                timezone = part.value;
            }
        });
        dateRange.setAttribute('title', timezone);
        dateRange.dataset.timezone = 'local'; // set data-timezone to some value to remove the dotted underline
    }
});

document.querySelectorAll('.markdown-input').forEach((markdownInput) => {
    let last = null;
    let gettingPreview = true;
    let needsPreviewRefresh = true;
    let sock = new WebSocket("wss://gefolge.org/api/v2/websocket");
    sock.binaryType = 'arraybuffer';
    let previewMarkdownEdit = () => {
        let newText = new TextEncoder().encode(markdownInput.value);
        let start = 0;
        for (; start < last.length && start < newText.length; start++) {
            if (last[start] != newText[start]) {
                break;
            }
        }
        let end = last.length;
        for (; end > start && end + newText.length - last.length > start; end--) {
            if (last[end - 1] != newText[end + newText.length - last.length - 1]) {
                break;
            }
        }
        let previewMarkdownEdit = new Uint8Array(end + newText.length - last.length - start + 25);
        previewMarkdownEdit[0] = 3; // ClientMessageV2::PreviewMarkdownEdit
        new DataView(previewMarkdownEdit.buffer).setBigUint64(1, BigInt(start));
        new DataView(previewMarkdownEdit.buffer).setBigUint64(9, BigInt(end));
        new DataView(previewMarkdownEdit.buffer).setBigUint64(17, BigInt(end + newText.length - last.length - start));
        previewMarkdownEdit.set(newText.slice(start, end + newText.length - last.length), 25);
        sock.send(previewMarkdownEdit);
        last = newText;
    };
    sock.onmessage = (event) => {
        switch (new DataView(event.data).getUint8(0)) {
            case 0: { // ServerMessageV2::Ping
                // ignore
                break;
            }
            case 1: { // ServerMessageV2::Error
                throw event.data; //TODO decode, display in preview element
            }
            case 5: { // ServerMessageV2::MarkdownPreview
                document.getElementById(markdownInput.id + '-preview').innerHTML = new TextDecoder().decode(event.data.slice(9));
                if (needsPreviewRefresh) {
                    needsPreviewRefresh = false;
                    previewMarkdownEdit();
                } else {
                    gettingPreview = false;
                }
                break;
            }
            default: {
                throw 'unexpected server message'; //TODO display in preview element
            }
        }
    };
    sock.onerror = (event) => {
        console.log(`WebSocket error: ${event}`);
        throw event; //TODO display in preview element
    };
    sock.onclose = (event) => {
        //TODO reconnect
        throw event; //TODO display in preview element
    };
    sock.onopen = () => {
        gettingPreview = false;
        needsPreviewRefresh = false;
        let apiKey = new TextEncoder().encode(markdownInput.dataset.apikey);
        let auth = new Uint8Array(apiKey.length + 9);
        auth[0] = 0; // ClientMessageV2::Auth
        new DataView(auth.buffer).setBigUint64(1, BigInt(apiKey.length));
        auth.set(apiKey, 9);
        sock.send(auth);
        last = new TextEncoder().encode(markdownInput.value);
        let previewMarkdown = new Uint8Array(last.length + 9);
        previewMarkdown[0] = 2; // ClientMessageV2::PreviewMarkdown
        new DataView(previewMarkdown.buffer).setBigUint64(1, BigInt(last.length));
        previewMarkdown.set(last, 9);
        sock.send(previewMarkdown);
    };
    markdownInput.addEventListener('input', (e) => {
        if (gettingPreview) {
            needsPreviewRefresh = true;
        } else {
            gettingPreview = true;
            previewMarkdownEdit();
        }
    });
});
