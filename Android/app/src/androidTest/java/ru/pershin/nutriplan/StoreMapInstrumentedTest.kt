package ru.pershin.nutriplan

import android.graphics.Bitmap
import android.webkit.WebView
import android.widget.Button
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.json.JSONTokener
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class StoreMapInstrumentedTest {
    @Test fun bundledMapLoadsAndManualLocationWorksWithoutPermission() {
        ActivityScenario.launch(StoreMapActivity::class.java).use { scenario ->
            fun javascript(script: String): String {
                val done = CountDownLatch(1)
                var value = ""
                scenario.onActivity { activity ->
                    activity.findViewById<WebView>(R.id.storeMapWebView).evaluateJavascript(script) {
                        value = it; done.countDown()
                    }
                }
                assertTrue(done.await(5, TimeUnit.SECONDS))
                return JSONTokener(value).nextValue().toString()
            }
            var ready = false
            repeat(30) {
                if (!ready) {
                    var controlsReady = false
                    scenario.onActivity { controlsReady = it.findViewById<Button>(R.id.mapChoosePointButton).isEnabled }
                    ready = controlsReady && javascript("typeof window.renderStores") == "function"
                    if (!ready) Thread.sleep(200)
                }
            }
            assertTrue("Bundled Leaflet must initialise without a CDN", ready)
            scenario.onActivity { activity ->
                assertFalse(activity.findViewById<Button>(R.id.mapRouteButton).isEnabled)
                assertTrue(activity.findViewById<WebView>(R.id.storeMapWebView).height > 0)
                activity.findViewById<Button>(R.id.mapChoosePointButton).performClick()
            }
            val hint = javascript("document.getElementById('hint').textContent")
            assertTrue("Manual location hint: $hint", hint.contains("Нажмите"))
            Thread.sleep(1500) // Let the first visible map tiles paint before visual inspection.
            val instrumentation = InstrumentationRegistry.getInstrumentation()
            val screenshot = instrumentation.uiAutomation.takeScreenshot()
            instrumentation.targetContext.openFileOutput("store-map-preview.png", 0).use {
                screenshot.compress(Bitmap.CompressFormat.PNG, 100, it)
            }
            screenshot.recycle()
        }
    }
}
