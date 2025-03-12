from app import create_app, db
from app.models import User, Patient, Consultation, MediaFile, UserSettings

app = create_app()

@app.shell_context_processor
def make_shell_context():
    return {
        'db': db,
        'User': User,
        'Patient': Patient,
        'Consultation': Consultation,
        'MediaFile': MediaFile,
        'UserSettings': UserSettings
    }

if __name__ == '__main__':
    app.run(debug=True)
