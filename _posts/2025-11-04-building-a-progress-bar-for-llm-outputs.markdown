---
layout: post
title: "Building a progress bar for LLM outputs"
date: 2025-11-04
---

<style>
  body {
    overflow-x: hidden !important;
  }
  .post-content {
    max-width: none !important;
    padding: 0 !important;
    margin: 0 !important;
  }
  #iframe-wrapper {
    width: 100%;
    overflow: hidden;
    position: relative;
  }
  #content-iframe {
    width: 100%;
    border: none;
    display: block;
    transform-origin: 0 0;
  }
</style>

<div id="iframe-wrapper">
  <iframe id="content-iframe" src="{{ site.baseurl }}/assets/llm-progress-bar.html"></iframe>
</div>

<script>
  // Auto-resize and scale iframe to fit without horizontal scroll
  const iframe = document.getElementById('content-iframe');
  const wrapper = document.getElementById('iframe-wrapper');
  
  iframe.onload = function() {
    try {
      const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
      
      const resizeIframe = () => {
        // Set height based on content
        const contentHeight = iframeDoc.documentElement.scrollHeight;
        const contentWidth = iframeDoc.documentElement.scrollWidth;
        const availableWidth = wrapper.offsetWidth;
        
        // Calculate scale to fit width
        const scale = contentWidth > availableWidth ? availableWidth / contentWidth : 1;
        
        // Apply scale and adjust height
        iframe.style.transform = `scale(${scale})`;
        iframe.style.width = contentWidth + 'px';
        iframe.style.height = contentHeight + 'px';
        wrapper.style.height = (contentHeight * scale) + 'px';
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