document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".markdown-image-select").forEach((button) => {
        button.addEventListener("click", () => {
            const altInput = button.closest(".markdown-image-card").querySelector(".markdown-image-alt");
            const alt = altInput.value.trim();
            if (!alt) {
                altInput.setCustomValidity("Informe o texto alternativo.");
                altInput.reportValidity();
                altInput.addEventListener("input", () => altInput.setCustomValidity(""), { once: true });
                return;
            }
            window.parent.postMessage(
                { type: "cms-markdown-image", url: button.dataset.imageUrl, alt },
                window.location.origin,
            );
        });
    });
});
