(() => {
    function jsonSyntaxHighlight(json) {
        json = json
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        return json.replace(
            /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
            function (match) {

                let cls = 'number';

                if (/^"/.test(match)) {
                    if (/:$/.test(match)) {
                        cls = 'key';
                    } else {
                        cls = 'string';

                        const hasMultiline = /\\n/.test(match);

                        match = match
                            .replace(/\\n/g, '\n')
                            .replace(/\\t/g, '\t');

                        if (hasMultiline) {
                            match = match.replace(
                                /^"([\s\S]*)"$/,
                                (_, content) => '"\n' + content + '\n"'
                            );
                        }
                    }
                } else if (/^(true|false)$/.test(match)) {
                    cls = 'boolean';
                } else if (/^null$/.test(match)) {
                    cls = 'null';
                }

                return `<span class="${cls}">${match}</span>`;
            }
        );
    }

    document.querySelectorAll('.qfc-pretty-field').forEach((block) => {
        const rawContent = block.textContent;
        const textContent = block.dataset.type === "json"
            ? jsonSyntaxHighlight(rawContent)
            : rawContent;

        block.classList.add('qfc-pretty-field-ready');

        block.innerHTML = `
            <div class="qfc-pretty-field-actions">
                <button type="button" class="qfc-toggle-wrap">Wrap</button>
                <button type="button" class="qfc-copy-raw">Copy</button>
            </div>
            <div class="qfc-code">${textContent}</div>
        `;

        block.querySelector('.qfc-toggle-wrap').addEventListener('click', () => {
            block.querySelector('.qfc-code').classList.toggle('qfc-wrapped');
        });

        block.querySelector('.qfc-copy-raw').addEventListener('click', async () => {
            await navigator.clipboard.writeText(rawContent);
        });
    });

})();
