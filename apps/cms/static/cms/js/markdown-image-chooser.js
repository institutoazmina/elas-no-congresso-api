document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll('textarea[data-image-chooser-url]').forEach((textarea) => {
        const editor = textarea.easymde;
        const toolbar = textarea.closest(".markdown-widget-wrapper")?.querySelector(".editor-toolbar");
        const imageButton = toolbar?.querySelector("button.image");
        if (!editor || !imageButton) return;

        const dialog = document.createElement("dialog");
        dialog.className = "markdown-gallery-dialog";
        dialog.innerHTML = `
            <div class="markdown-gallery-header">
                <strong>Galeria de imagens</strong>
                <button type="button" aria-label="Fechar galeria">×</button>
            </div>
            <iframe title="Galeria de imagens"></iframe>
        `;
        document.body.appendChild(dialog);

        const iframe = dialog.querySelector("iframe");
        dialog.querySelector("button").addEventListener("click", () => dialog.close());
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) dialog.close();
        });

        const galleryButton = imageButton.cloneNode(false);
        galleryButton.title = "Galeria de imagens";
        galleryButton.setAttribute("aria-label", "Abrir galeria de imagens");
        galleryButton.innerHTML = '<span class="material-symbols-outlined">perm_media</span>';
        galleryButton.addEventListener("click", () => {
            if (!iframe.src) iframe.src = textarea.dataset.imageChooserUrl;
            dialog.showModal();
        });
        imageButton.replaceWith(galleryButton);

        window.addEventListener("message", (event) => {
            if (
                event.origin !== window.location.origin ||
                event.source !== iframe.contentWindow ||
                event.data?.type !== "cms-markdown-image"
            ) return;

            const alt = event.data.alt.replaceAll("\\", "\\\\").replaceAll("]", "\\]");
            editor.codemirror.replaceSelection(`![${alt}](${event.data.url})`);
            editor.codemirror.focus();
            dialog.close();
        });
    });
});
