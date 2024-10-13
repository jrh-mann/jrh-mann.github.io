---
layout: post
title: Why are we using tokens?
date: 2024-10-12 00:00:00 +0300
description: This is a post that will document my project to create a new type of LLM that autoregresses over embedding space rather than token space
img: software.jpg # Add image post (optional)
tags: [LLMs] # add tag
---
In a previous project I wrote a transformer from scratch. It was slow, painful, and didn't really work. I'm not going to write a post about it so instead I'll leave it in a [github repo](https://github.com/broverfitter/transformer_from_scratch). Although it was unsuccessful in almost every sense of the word, it really helped me understand transformers, understand that they're magic. The process itself - even in its simplest 2017 form - feels like the product of divine revelation. Even then I felt that there was something, maybe not missing but certainly wrong. It's only recently I've been able to articulate my confusion as **why are we using tokens?**.

I will now try to elaborate on what I mean by this, forgive me if parts feel elementary, I like to fall back to a basic every now and again just to keep myself from wandering. A transformer outputs some probability distribution over a load of possible next tokens, using some context tokens as input. All tokens are stored in precise fixed locations in embedding space. In training we hope these locations move to reflect human semantic space and, fortunately, this seems to be true. Unfortunately, no matter how perfect the embedding/mapping gets it will always suffer from the ambiguity inherent to words. One word can have several meanings and in embedding space there is no way to represent this. We currently solve this problem with context; the model uses all prior words to work out the meaning - this process, however, requires enourmous amounts of compute. I think this is the key inefficiency that bothered me, in each pass of the transformer it expends compute on working out the same semantic relationships.  

What if instead we allowed tokens to be semantically self-containing. 


Here I outline some key things I can envision this causing.
* A much deeper semantic understanding in smaller models. At present 
* Much improved planning and agenticism
* Bedwetting from safety and control people