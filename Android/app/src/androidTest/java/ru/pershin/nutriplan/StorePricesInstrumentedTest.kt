package ru.pershin.nutriplan

import android.graphics.Bitmap
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.view.View
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class StorePricesInstrumentedTest {
    @Test fun rejectsForeignStoreLinksBeforeNetworkOrPermissionRequests() {
        ActivityScenario.launch(StorePricesActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val link = activity.findViewById<EditText>(R.id.magnitStoreLinkInput)
                link.setText("https://example.org/product/123?shopCode=992301&shopType=dostavka")
                activity.findViewById<Button>(R.id.findPlanProductsButton).performClick()
                assertNotNull(link.error)
                assertEquals(View.GONE, activity.findViewById<ProgressBar>(R.id.storePricesProgress).visibility)
                link.setText("")
                link.error = null
            }
            val instrumentation = InstrumentationRegistry.getInstrumentation()
            instrumentation.waitForIdleSync()
            val screenshot = instrumentation.uiAutomation.takeScreenshot()
            instrumentation.targetContext.openFileOutput("magnit-prices-preview.png", 0).use {
                screenshot.compress(Bitmap.CompressFormat.PNG, 100, it)
            }
            screenshot.recycle()
        }
    }
}
