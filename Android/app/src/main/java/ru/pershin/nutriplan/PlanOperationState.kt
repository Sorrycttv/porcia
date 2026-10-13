package ru.pershin.nutriplan

import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import retrofit2.Call

/** Keep a menu mutation alive across rotation; the new screen reloads after it finishes. */
class PlanOperationState : ViewModel() {
    val pending = MutableLiveData(false)
    var request: Call<*>? = null

    fun complete() {
        request = null
        pending.value = false
    }

    override fun onCleared() {
        request?.cancel()
        request = null
    }
}
