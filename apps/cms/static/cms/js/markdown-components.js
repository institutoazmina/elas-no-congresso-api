document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll('textarea[id^="markdown-"]').forEach((textarea) => {
        const editor = textarea.easymde;
        const toolbar = textarea.closest(".markdown-widget-wrapper")?.querySelector(".editor-toolbar");
        if (!editor || !toolbar) return;

        const card = (content = "#### Título do card\n\nConteúdo do card.") =>
            `::: card\n${content}\n:::`;
        const group = (columns) =>
            `:::: cards ${columns}\n\n${Array.from({ length: columns }, () => card()).join("\n\n")}\n\n::::`;
        const addButton = (label, snippet) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "unfold-markdown-button markdown-component-button";
            button.textContent = label;
            button.title = label;
            button.setAttribute("aria-label", label);
            button.addEventListener("click", () => {
                const selected = editor.codemirror.getSelection().trim();
                editor.codemirror.replaceSelection(`\n\n${snippet(selected)}\n\n`);
                editor.codemirror.focus();
            });
            toolbar.appendChild(button);
        };

        addButton("2 cards", () => group(2));
        addButton("3 cards", () => group(3));
        addButton("Adicionar card", (selected) => card(selected || undefined));
    });
});
