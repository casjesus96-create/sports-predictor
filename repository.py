import os
from supabase import create_client
def save_prediction(payload):
    url,key=os.getenv("SUPABASE_URL"),os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:return {"persisted":False,"reason":"Supabase variables not configured"}
    result=create_client(url,key).table("prediction_snapshots").insert(payload).execute()
    return {"persisted":True,"data":result.data}
