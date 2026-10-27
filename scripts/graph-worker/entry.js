/* This entry bundles only the worker supervisor, never a second graph store. */
import FA2Layout from "graphology-layout-forceatlas2/worker";
window.ThreadDeskForceAtlas2 = (graph, options) => new FA2Layout(graph, options);
