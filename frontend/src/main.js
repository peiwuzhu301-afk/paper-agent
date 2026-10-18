import { createApp } from 'vue'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import App from './App.vue'
import './style.css'

// 供组件在渲染报告后调用 KaTeX 渲染公式
window.katex = katex

createApp(App).mount('#app')
window.dispatchEvent(new Event('katex-ready'))
