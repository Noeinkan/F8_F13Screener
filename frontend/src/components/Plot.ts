/**
 * The Plotly React component, built from plotly.js core plus only the trace
 * types this dashboard draws.
 *
 * `import Plot from "react-plotly.js"` pulls in the full plotly.js bundle
 * (every trace type, maps, WebGL: ~4.5 MB minified). Charts.tsx uses three:
 * - bar     BarChart, HorizontalBarChart, GroupedBarChart
 * - scatter LineChart, LanesChart (lines, markers, text) — core registers it
 * - sankey  SankeyChart
 * A chart with a trace type not registered here renders empty, so add the
 * module below when Charts.tsx gains a new `type:`.
 */
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js/lib/core";
import bar from "plotly.js/lib/bar";
import sankey from "plotly.js/lib/sankey";

Plotly.register([bar, sankey]);

export const Plot = createPlotlyComponent(Plotly);
