document.querySelectorAll('.datetime').forEach(function(dateTime) {
    var timestamp = new Date(parseInt(dateTime.dataset.timestamp));
    var longFormat = dateTime.dataset.long == 'true';
    if ('timezone' in dateRange.dataset) {
        // preserve specified timezone but otherwise format according to user locale
        dateTime.textContent = timestamp.toLocaleString([], {
            dateStyle: longFormat ? 'full' : 'medium',
            timeStyle: longFormat ? 'full' : 'short',
            timeZone: dateRange.dataset.timezone,
        });
        var timezone = 'unbekannte Zeitzone';
        Intl.DateTimeFormat([], {timeZoneName: 'long', timeZone: dateRange.dataset.timezone}).formatToParts(timestamp).forEach(function(part) {
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
