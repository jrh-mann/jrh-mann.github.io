---
layout: post
title: "Building a progress bar for LLM outputs"
date: 2025-11-04
---

<style>
  .post-content {
    max-width: none !important;
    padding: 0 !important;
    margin: 0 !important;
  }
  #content-iframe {
    width: calc(100vw - 250px);
    border: none;
    overflow: hidden;
    display: block;
    margin-left: 0;
    position: relative;
    left: 0;
  }
</style>

<iframe id="content-iframe" src="{{ site.baseurl }}/assets/llm-progress-bar.html"></iframe>

<script>
  // Auto-resize iframe to content height
  const iframe = document.getElementById('content-iframe');
  iframe.onload = function() {
    try {
      const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
      const resizeIframe = () => {
        iframe.style.height = iframeDoc.documentElement.scrollHeight + 'px';
      };
      resizeIframe();
      // Watch for dynamic content changes
      if (iframeDoc.body) {
        new MutationObserver(resizeIframe).observe(iframeDoc.body, {
          childList: true,
          subtree: true,
          attributes: true
        });
      }
      // Also resize on window resize
      window.addEventListener('resize', resizeIframe);
    } catch(e) {
      // Fallback if cross-origin restrictions apply
      iframe.style.height = '3000px';
    }
  };
</script>