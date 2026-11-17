(() => {
    'use strict';

    // Modern Plesk database cards omit the hook's newWindow property.
    // Decorate only our existing launch links; native clicks keep their behavior.
    const selector = 'a[href^="/tabularis/open/"]';
    const decorate = (root) => {
        if (!(root instanceof Element)) return;
        const links = root.matches(selector) ? [root] : [];
        links.push(...root.querySelectorAll(selector));
        for (const link of links) {
            if (!/^\/tabularis\/open\/[1-9][0-9]*$/.test(link.getAttribute('href'))) continue;
            link.target = '_blank';
            link.relList.add('noopener', 'noreferrer');
        }
    };

    decorate(document.documentElement);
    const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            if (mutation.type === 'attributes') decorate(mutation.target);
            else mutation.addedNodes.forEach(decorate);
        }
    });
    observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['href'],
    });
})();
