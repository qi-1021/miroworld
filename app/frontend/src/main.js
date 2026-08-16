import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import i18n from './i18n'

// LGGC：纯 CSS 液态玻璃（GuoChen Wang, MIT）
import './assets/lggc/lggc.css'

const app = createApp(App)

app.use(router)
app.use(i18n)

app.mount('#app')
