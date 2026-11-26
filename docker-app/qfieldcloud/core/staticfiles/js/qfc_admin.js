// Chart.js draws dark tooltips on both themes, so use Unfold's theme colors, read on every draw.
// Unfold loads Chart.js before `UNFOLD["SCRIPTS"]`, so these defaults apply to every chart.
if (window.Chart) {
    const themeColor = (lightVariable, darkVariable) => () => {
        let variable = lightVariable;
        if (document.documentElement.classList.contains('dark')) {
            variable = darkVariable;
        }

        return getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
    };
    // the color of the axis ticks and legend labels
    Chart.defaults.color = themeColor('--color-base-400', '--color-base-400');

    const tooltip = Chart.defaults.plugins.tooltip;

    tooltip.backgroundColor = themeColor('--color-white', '--color-base-800');
    tooltip.titleColor = themeColor('--color-font-important-light', '--color-font-important-dark');
    tooltip.bodyColor = themeColor('--color-font-default-light', '--color-font-default-dark');
    tooltip.borderColor = themeColor('--color-base-200', '--color-base-700');
    tooltip.borderWidth = 1;
}

// Unfold loads `UNFOLD["SCRIPTS"]` in `<head>`, so wait for the page content
document.addEventListener('DOMContentLoaded', () => {
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

});
