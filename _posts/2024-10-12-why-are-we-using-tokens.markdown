---
layout: post
title: CV
date: 2025-01-01 00:00:00 +0300
description: My CV
---

<div id="pdf-viewer"></div>
<script>
  var url = "{{ site.baseurl }}/assets/JamesMannCV.pdf";
  var loadingTask = pdfjsLib.getDocument(url);
  loadingTask.promise.then(function(pdf) {
    pdf.getPage(1).then(function(page) {
      var scale = 1.5;
      var viewport = page.getViewport({ scale: scale });
      var canvas = document.createElement("canvas");
      var context = canvas.getContext("2d");
      canvas.height = viewport.height;
      canvas.width = viewport.width;
      document.getElementById("pdf-viewer").appendChild(canvas);
      page.render({ canvasContext: context, viewport: viewport });
    });
  });
</script>