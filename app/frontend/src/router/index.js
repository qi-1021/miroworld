import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home
  },
  {
    path: '/process/:projectId',
    name: 'Process',
    component: () => import('../views/MainView.vue'),
    props: true
  },
  {
    path: '/world/:projectId',
    name: 'WorldSetup',
    component: () => import('../views/WorldSetupView.vue'),
    props: true
  },
  {
    path: '/simulation/:simulationId',
    name: 'Simulation',
    component: () => import('../views/SimulationView.vue'),
    props: true
  },
  {
    path: '/simulation/:simulationId/start',
    name: 'SimulationRun',
    component: () => import('../views/SimulationRunView.vue'),
    props: true
  },
  {
    path: '/report/:reportId',
    name: 'Report',
    component: () => import('../views/ReportView.vue'),
    props: true
  },
  {
    path: '/interaction/:reportId',
    name: 'Interaction',
    component: () => import('../views/InteractionView.vue'),
    props: true
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
