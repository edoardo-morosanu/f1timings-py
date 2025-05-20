import uvicorn

if __name__ == "__main__":
    print("Starting F1 Timings application...")
    # Use string reference - this tells uvicorn to load the module correctly
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)
